/**
 * Offline-first order queue (IndexedDB) + sync on "online".
 * Store: offline_orders — { client_request_id, payload, status, retry_count }
 * Status: pending | synced | failed — rows are removed from IDB only after HTTP 201 (ACK).
 * Retries: max 3 after first attempt; backoff 1s → 2s → 5s (cap).
 * Backend remains source of truth; payload is only a transport cache.
 */
(function () {
  const DB_NAME = "hayaflash-offline-orders";
  const STORE = "offline_orders";
  const DB_VERSION = 2;
  /** After the first failed POST, allow up to 3 additional attempts (4 POSTs total). */
  const MAX_RETRIES_AFTER_FIRST = 3;
  const MIN_ADDRESS_LENGTH = 10;
  const GEO_TIMEOUT_MS = 10000;

  var geoState = {
    lat: null,
    lng: null,
    accuracy: null,
    method: "manual",
  };

  function backoffDelayMs(attemptIndex) {
    if (attemptIndex <= 1) {
      return 1000;
    }
    if (attemptIndex === 2) {
      return 2000;
    }
    return 5000;
  }

  function openDb() {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onerror = function () {
        reject(req.error);
      };
      req.onsuccess = function () {
        resolve(req.result);
      };
      req.onupgradeneeded = function (e) {
        var db = e.target.result;
        if (db.objectStoreNames.contains("pending")) {
          db.deleteObjectStore("pending");
        }
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: "client_request_id" });
        }
      };
    });
  }

  function putRecord(rec) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, "readwrite");
        tx.objectStore(STORE).put(rec);
        tx.oncomplete = function () {
          resolve();
        };
        tx.onerror = function () {
          reject(tx.error);
        };
      });
    });
  }

  function allRecords() {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, "readonly");
        var q = tx.objectStore(STORE).getAll();
        q.onsuccess = function () {
          resolve(q.result || []);
        };
        q.onerror = function () {
          reject(q.error);
        };
      });
    });
  }

  function deleteOne(clientRequestId) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, "readwrite");
        tx.objectStore(STORE).delete(clientRequestId);
        tx.oncomplete = function () {
          resolve();
        };
        tx.onerror = function () {
          reject(tx.error);
        };
      });
    });
  }

  function wait(ms) {
    return new Promise(function (r) {
      setTimeout(r, ms);
    });
  }

  function postOrder(apiUrl, body) {
    return fetch(apiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    }).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try {
          data = text ? JSON.parse(text) : null;
        } catch (_) {}
        return { ok: res.ok, status: res.status, data: data, raw: text };
      });
    });
  }

  function setGeoStatus(msg, kind) {
    var el = document.getElementById("geo-status");
    if (!el) return;
    el.textContent = msg;
    el.className = kind || "info";
  }

  function captureLocation() {
    return new Promise(function (resolve) {
      if (!navigator.geolocation) {
        resolve({ lat: null, lng: null, accuracy: null, method: "manual" });
        return;
      }
      var settled = false;
      var timer = setTimeout(function () {
        if (settled) return;
        settled = true;
        resolve({ lat: null, lng: null, accuracy: null, method: "timeout" });
      }, GEO_TIMEOUT_MS);

      navigator.geolocation.getCurrentPosition(
        function (pos) {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve({
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
            method: "gps",
          });
        },
        function () {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve({ lat: null, lng: null, accuracy: null, method: "denied" });
        },
        { enableHighAccuracy: true, timeout: GEO_TIMEOUT_MS, maximumAge: 30000 }
      );
    });
  }

  function reverseGeocode(lat, lng) {
    var url =
      "https://nominatim.openstreetmap.org/reverse?format=json&lat=" +
      encodeURIComponent(lat) +
      "&lon=" +
      encodeURIComponent(lng);
    var controller = new AbortController();
    var timer = setTimeout(function () {
      controller.abort();
    }, 5000);
    return fetch(url, {
      signal: controller.signal,
      headers: { Accept: "application/json", "User-Agent": "HayaFlash/1.0 (order delivery)" },
    })
      .then(function (res) {
        clearTimeout(timer);
        if (!res.ok) return null;
        return res.json();
      })
      .then(function (data) {
        if (!data || !data.display_name) return null;
        return data.display_name;
      })
      .catch(function () {
        clearTimeout(timer);
        return null;
      });
  }

  function wireGeoButton() {
    var btn = document.getElementById("geo-btn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      btn.disabled = true;
      setGeoStatus("Détection de votre position…", "info");
      captureLocation().then(function (loc) {
        geoState.lat = loc.lat;
        geoState.lng = loc.lng;
        geoState.accuracy = loc.accuracy;
        geoState.method = loc.method;

        if (loc.method === "gps" && loc.lat != null && loc.lng != null) {
          var msg = "Position GPS enregistrée.";
          if (loc.accuracy != null && loc.accuracy > 500) {
            msg = "Position imprécise — vérifiez l'adresse ci-dessous.";
            setGeoStatus(msg, "warn");
          } else {
            setGeoStatus("✓ " + msg, "ok");
          }
          return reverseGeocode(loc.lat, loc.lng).then(function (suggested) {
            if (suggested) {
              var addrEl = document.getElementById("cust-address");
              if (addrEl && !addrEl.value.trim()) {
                addrEl.value = suggested;
              }
            }
          });
        }
        if (loc.method === "denied") {
          setGeoStatus("GPS refusé — entrez votre adresse manuellement.", "info");
        } else if (loc.method === "timeout") {
          setGeoStatus("GPS indisponible — entrez votre adresse manuellement.", "info");
        } else {
          setGeoStatus("Entrez votre adresse manuellement.", "info");
        }
      }).finally(function () {
        btn.disabled = false;
      });
    });
  }

  function buildDeliveryBlock(addressText, notes) {
    var block = {
      address_text: addressText,
      geo_method: geoState.method || "manual",
      delivery_notes: notes || "",
    };
    if (geoState.lat != null && geoState.lng != null) {
      block.latitude = geoState.lat;
      block.longitude = geoState.lng;
    }
    if (geoState.accuracy != null) {
      block.geo_accuracy = geoState.accuracy;
    }
    return block;
  }

  function buildPayload(name, phone, qty, fs, pr, client_request_id, shareRef, trackingSrc, addressText, notes) {
    var body = {
      name: name,
      phone: phone,
      quantity: qty,
      flash_sale_id: parseInt(fs, 10),
      product_id: parseInt(pr, 10),
      client_request_id: client_request_id,
      delivery: buildDeliveryBlock(addressText, notes),
    };
    if (shareRef) {
      body.share_ref = shareRef;
    }
    if (trackingSrc) {
      body.src = trackingSrc;
    }
    return body;
  }

  function makeQueueRecord(client_request_id, payload) {
    return {
      client_request_id: client_request_id,
      payload: payload,
      status: "pending",
      retry_count: 0,
    };
  }

  /**
   * POST until 201/200 (delete row = ACK), 400 (failed, no retry), or retries exhausted.
   */
  function syncOneRecord(rec, apiUrl) {
    if (rec.status !== "pending") {
      return Promise.resolve();
    }
    var failures = 0;
    function oneRound() {
      return postOrder(apiUrl, rec.payload)
        .then(function (out) {
          if (out.ok && (out.status === 201 || out.status === 200)) {
            rec.status = "synced";
            return deleteOne(rec.client_request_id);
          }
          if (out.status === 400) {
            rec.status = "failed";
            return putRecord(rec);
          }
          failures += 1;
          rec.retry_count = failures;
          if (failures > MAX_RETRIES_AFTER_FIRST) {
            rec.status = "failed";
            return putRecord(rec);
          }
          return putRecord(rec).then(function () {
            return wait(backoffDelayMs(failures)).then(oneRound);
          });
        })
        .catch(function () {
          failures += 1;
          rec.retry_count = failures;
          if (failures > MAX_RETRIES_AFTER_FIRST) {
            rec.status = "failed";
            return putRecord(rec);
          }
          return putRecord(rec).then(function () {
            return wait(backoffDelayMs(failures)).then(oneRound);
          });
        });
    }
    return oneRound();
  }

  function syncQueue(apiUrl) {
    return allRecords().then(function (rows) {
      var pending = rows.filter(function (r) {
        return r.status === "pending";
      });
      var chain = Promise.resolve();
      pending.forEach(function (rec) {
        chain = chain.then(function () {
          return syncOneRecord(rec, apiUrl);
        });
      });
      return chain;
    });
  }

  function showReferralPanel(referral) {
    if (!referral || !referral.available) return;
    var panel = document.getElementById("referral-panel");
    var sub = document.getElementById("referral-sub");
    var waInvite = document.getElementById("referral-wa-invite");
    var waProduct = document.getElementById("referral-wa-product");
    var sellerLink = document.getElementById("referral-seller");
    if (!panel || !sub) return;
    sub.textContent =
      referral.product_name +
      " — partagez HayaFlash et aidez " +
      (referral.seller_name || "ce vendeur") +
      " à grandir.";
    if (waInvite && referral.whatsapp_invite_url) {
      waInvite.href = referral.whatsapp_invite_url;
      waInvite.style.display = "block";
    }
    if (waProduct && referral.whatsapp_url) {
      waProduct.href = referral.whatsapp_url;
      waProduct.style.display = "block";
    }
    if (sellerLink && referral.seller_url) {
      sellerLink.href = referral.seller_url;
      sellerLink.style.display = "block";
    }
    panel.style.display = "block";
  }

  function resetGeoState() {
    geoState = { lat: null, lng: null, accuracy: null, method: "manual" };
    setGeoStatus("", "info");
  }

  function wireForm() {
    var form = document.getElementById("client-order-form");
    if (!form) return;
    var apiUrl = window.HF_ORDER_API_URL;
    var statusEl = document.getElementById("order-status");
    function setStatus(msg, ok) {
      statusEl.textContent = msg;
      statusEl.style.color = ok ? "#166534" : "#b91c1c";
    }

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (!apiUrl) return;
      var fs = form.getAttribute("data-flash-sale-id");
      var pr = form.getAttribute("data-product-id");
      var shareRef = form.getAttribute("data-share-ref") || window.HF_SHARE_REF || "";
      var trackingSrc = form.getAttribute("data-tracking-src") || window.HF_TRACKING_SRC || "direct";
      if (!fs || !pr) {
        setStatus("Paramètres produit manquants dans l'URL.", false);
        return;
      }
      var name = document.getElementById("cust-name").value.trim();
      var phone = document.getElementById("cust-phone").value.trim();
      var address = document.getElementById("cust-address").value.trim();
      var notes = document.getElementById("cust-notes").value.trim();
      var qtyRaw = document.getElementById("cust-qty").value.trim();
      var qty = parseInt(qtyRaw, 10);
      if (!name || !phone || !Number.isFinite(qty) || qty < 1) {
        setStatus("Vérifiez le nom, le téléphone et la quantité (≥ 1).", false);
        return;
      }
      if (address.length < MIN_ADDRESS_LENGTH) {
        setStatus("L'adresse doit contenir au moins " + MIN_ADDRESS_LENGTH + " caractères.", false);
        return;
      }
      var client_request_id = crypto.randomUUID();
      var payload = buildPayload(
        name,
        phone,
        qty,
        fs,
        pr,
        client_request_id,
        shareRef,
        trackingSrc,
        address,
        notes
      );
      var record = makeQueueRecord(client_request_id, payload);

      setStatus("Commande enregistrée (confirmation en cours)…", true);

      if (!navigator.onLine) {
        putRecord(record).then(function () {
          setStatus(
            "Hors ligne — commande en file sur cet appareil. Synchronisation automatique au retour du réseau.",
            true
          );
        });
        return;
      }

      postOrder(apiUrl, payload)
        .then(function (out) {
          if (out.ok && (out.status === 201 || out.status === 200)) {
            setStatus("Commande reçue. Merci !", true);
            form.reset();
            document.getElementById("cust-qty").value = "1";
            resetGeoState();
            if (out.data && out.data.referral) {
              showReferralPanel(out.data.referral);
            }
            return;
          }
          if (out.status === 429) {
            setStatus("Trop de tentatives. Patientez une minute puis réessayez.", false);
            return;
          }
          if (out.status === 400) {
            var msg = out.data ? JSON.stringify(out.data) : out.raw || "Données invalides.";
            setStatus(msg, false);
            return;
          }
          return putRecord(record).then(function () {
            setStatus(
              "Erreur serveur — commande conservée sur cet appareil. Nouvel essai automatique.",
              true
            );
          });
        })
        .catch(function () {
          return putRecord(record).then(function () {
            setStatus(
              "Réseau indisponible — commande conservée. Synchronisation automatique.",
              true
            );
          });
        });
    });

    window.addEventListener("online", function () {
      syncQueue(apiUrl);
    });
    if (navigator.onLine) {
      syncQueue(apiUrl);
    }
  }

  function init() {
    wireGeoButton();
    wireForm();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
