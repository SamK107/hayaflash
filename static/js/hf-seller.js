/* HayaFlash — pages vendeur (formulaires, Publication rapide, paiement).
 *
 * Charge par flash_sales/create.html, products/product_form.html,
 * products/quick_publish.html et subscriptions/payment_pending.html. Ex-scripts
 * inline deplaces ici pour la CSP (GOVERNANCE_SECURITE.md categorie 4). Les
 * composants Alpine restent des fonctions globales (x-data="audioRec(...)").
 */

/* ── Envoi de formulaire avec fichier capture hors <input> ──
 * <form data-hf-file-fallback="champ" data-hf-file-var="__hfXxx"> : si le
 * navigateur n'a pas pu injecter la photo dans l'input (DataTransfer absent,
 * iOS < 15), le composant Alpine la garde dans window[data-hf-file-var] ; on
 * poste alors le formulaire en fetch avec ce fichier. */
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('form[data-hf-file-fallback]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      var file = window[form.dataset.hfFileVar];
      if (!file) return;
      e.preventDefault();
      var fd = new FormData(form);
      fd.set(form.dataset.hfFileFallback, file, file.name);
      fetch(form.action || window.location.pathname, { method: 'POST', body: fd })
        .then(function (r) {
          if (r.redirected) { window.location.href = r.url; return null; }
          return r.text();
        })
        .then(function (html) {
          if (!html) return;
          document.open(); document.write(html); document.close();
        });
    });
  });
});

/* ── Paiement en attente : recharge toutes les 10 s ── */
document.addEventListener('DOMContentLoaded', function () {
  var el = document.querySelector('[data-hf-autoreload]');
  if (el) setTimeout(function () { location.reload(); }, Number(el.dataset.hfAutoreload) || 10000);
});

/* Composant Alpine audioRec(fieldName) — enregistreur micro générique */
function audioRec(fieldName) {
  return {
    recording: false,
    hasAudio: false,
    audioUrl: null,
    mediaRecorder: null,
    chunks: [],
    elapsed: 0,
    _timer: null,
    fieldName: fieldName,
    init() { lucide.createIcons(); },
    formatTime(s) {
      const m = Math.floor(s/60);
      const sec = s % 60;
      return (m<10?'0':'')+m+':'+(sec<10?'0':'')+sec;
    },
    async start() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        alert('Votre appareil ne supporte pas l\'enregistrement audio.'); return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.chunks = [];
        this.elapsed = 0;
        const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/ogg';
        this.mediaRecorder = new MediaRecorder(stream, { mimeType });
        this.mediaRecorder.ondataavailable = e => { if (e.data.size > 0) this.chunks.push(e.data); };
        this.mediaRecorder.onstop = () => {
          stream.getTracks().forEach(t => t.stop());
          const blob = new Blob(this.chunks, { type: mimeType });
          this.audioUrl = URL.createObjectURL(blob);
          this.hasAudio = true;
          /* Injecter dans le <input type="file"> caché */
          const ext = mimeType.includes('webm') ? 'webm' : 'ogg';
          const file = new File([blob], 'vocal-' + Date.now() + '.' + ext, { type: mimeType });
          try {
            const dt = new DataTransfer();
            dt.items.add(file);
            this.$refs.audioInput.files = dt.files;
          } catch(e) {
            console.warn('DataTransfer audio not supported');
          }
          lucide.createIcons();
        };
        this.mediaRecorder.start();
        this.recording = true;
        this._timer = setInterval(() => this.elapsed++, 1000);
        lucide.createIcons();
      } catch(err) {
        alert('Micro inaccessible : ' + (err.message || err.name));
      }
    },
    stop() {
      if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
        this.mediaRecorder.stop();
      }
      clearInterval(this._timer);
      this.recording = false;
    },
    clear() {
      this.hasAudio = false;
      this.audioUrl = null;
      this.chunks = [];
      this.$refs.audioInput.value = '';
      lucide.createIcons();
    }
  };
}

/* ── Publication rapide (products/quick_publish.html) ── */
function quickPublishApp() {
  const cfg = (document.getElementById('qp-config') || {}).dataset || {};
  return {
    rows: [],
    dragOver: false,
    uploadingCount: 0,
    loading: false,
    message: '',
    messageType: 'success',
    showDiscount: false,
    showStock: false,
    discountPercent: 10,
    defaultStock: 10,
    duplicateFromId: '',

    // URLs d'API posees par le template sur <div id="qp-config" data-*> (CSP :
    // aucune interpolation Django dans le JS).
    apiCatalogUrl: cfg.catalogUrl,
    apiBulkUpdateUrl: cfg.bulkUpdateUrl,
    apiBulkUploadUrl: cfg.bulkUploadUrl,
    apiAssignImageUrl: cfg.assignImageUrl,
    apiDuplicateUrl: cfg.duplicateUrl,
    apiArchiveProductUrl: cfg.archiveProductUrl,
    apiDeleteProductUrl: cfg.deleteProductUrl,
    showArchived: false,
    saleDetailUrl: cfg.saleDetailUrl,
    pendingUploadRow: null,

    get selectedCount() {
      return this.rows.filter(r => r.selected).length;
    },

    csrfToken() {
      const m = document.cookie.match(/csrftoken=([^;]+)/);
      return m ? m[1] : '';
    },

    async init() {
      await this.loadCatalog();
    },

    // lucide.createIcons() (templates/base.html) ne tourne qu'au chargement
    // initial de la page et apres un swap htmx -- cette page n'utilise pas
    // htmx pour sa grille (Alpine seul), donc toute icone ajoutee/mise a
    // jour dynamiquement (lignes chargees en async, nouvelle ligne, bascule
    // masque/actif...) restait une balise <i> vide, invisible. On force
    // une passe lucide apres chaque mutation qui ajoute ou change une icone.
    refreshIcons() {
      this.$nextTick(() => { if (window.lucide) lucide.createIcons(); });
    },

    async loadCatalog() {
      try {
        const url = this.apiCatalogUrl + (this.showArchived
          ? (this.apiCatalogUrl.includes('?') ? '&' : '?') + 'include_archived=1'
          : '');
        const res = await fetch(url, { headers: { 'Accept': 'application/json' }, cache: 'no-store' });
        if (!res.ok) throw new Error('Erreur de chargement du catalogue.');
        const data = await res.json();
        const existingByProductId = {};
        (data.flash_sale_products || []).forEach(fsp => { existingByProductId[fsp.product.id] = fsp; });

        this.rows = (data.catalog || []).map(p => {
          const link = existingByProductId[p.id];
          return {
            key: 'p' + p.id,
            isNew: false,
            product_id: p.id,
            name: p.name,
            price: parseFloat(p.price),
            image_url: (p.media && p.media[0]) ? p.media[0].file_url : null,
            selected: !!link,
            promo_price: link && link.promo_price ? parseFloat(link.promo_price) : null,
            stock: p.stock_available,
            display_order: link ? link.display_order : 0,
            isActive: p.is_active,
          };
        });
        this.refreshIcons();
      } catch (e) {
        this.setMessage(e.message || 'Erreur de chargement.', 'error');
      }
    },

    addBlankRow(overrides) {
      const row = Object.assign({
        key: 'new' + Date.now() + Math.random(),
        isNew: true,
        product_id: null,
        name: '',
        price: 0,
        image_url: null,
        pendingFile: null,  // File en attente d'envoi, posee via une photo
        // groupee non rattachee (ni par nom, ni par position) : le produit
        // n'existe pas encore, la photo ne peut etre envoyee au serveur
        // qu'apres sa creation (cf. publish()).
        selected: true,
        promo_price: null,
        stock: 0,
        display_order: 0,
        isActive: true,
      }, overrides || {});
      this.rows.unshift(row);
      this.refreshIcons();
      return row;
    },

    removeRow(idx) {
      // Ligne pas encore publiee (aucun produit cree cote serveur) : simple
      // retrait local, rien a synchroniser.
      this.rows.splice(idx, 1);
    },

    async archiveRow(idx) {
      const row = this.rows[idx];
      if (row.isNew) { this.removeRow(idx); return; }
      if (!confirm(`Masquer « ${row.name} » ? Il n'apparaitra plus dans cette liste (ni dans les prochaines ventes) mais rien n'est supprime -- vous pourrez le reafficher via « Voir les produits masqués ».`)) return;

      try {
        const res = await fetch(this.apiArchiveProductUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrfToken() },
          body: JSON.stringify({ product_id: row.product_id, is_active: false }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Erreur pendant le masquage.');
        this.rows.splice(idx, 1);
        this.setMessage(`« ${row.name} » masqué.`, 'success');
      } catch (e) {
        this.setMessage(e.message, 'error');
      }
    },

    async reactivateRow(idx) {
      const row = this.rows[idx];
      try {
        const res = await fetch(this.apiArchiveProductUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrfToken() },
          body: JSON.stringify({ product_id: row.product_id, is_active: true }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Erreur pendant la réactivation.');
        row.isActive = true;
        this.refreshIcons();
        this.setMessage(`« ${row.name} » réaffiché.`, 'success');
      } catch (e) {
        this.setMessage(e.message, 'error');
      }
    },

    async deleteRow(idx) {
      const row = this.rows[idx];
      if (row.isNew) { this.removeRow(idx); return; }
      if (!confirm(`Supprimer définitivement « ${row.name} » ? Cette action est irréversible. Si ce produit a déjà été vendu, la suppression sera refusée -- utilisez plutôt « masquer » dans ce cas.`)) return;

      try {
        const res = await fetch(this.apiDeleteProductUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrfToken() },
          body: JSON.stringify({ product_id: row.product_id }),
        });
        if (res.status === 409) {
          const data = await res.json();
          this.setMessage(data.detail, 'warning');
          return;
        }
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || 'Erreur pendant la suppression.');
        }
        this.rows.splice(idx, 1);
        this.setMessage(`« ${row.name} » supprimé.`, 'success');
      } catch (e) {
        this.setMessage(e.message, 'error');
      }
    },

    async toggleShowArchived() {
      this.showArchived = !this.showArchived;
      await this.loadCatalog();
    },

    toggleAll(checked) {
      this.rows.forEach(r => { r.selected = checked; });
    },

    applyDiscount() {
      const factor = 1 - (this.discountPercent || 0) / 100;
      this.rows.filter(r => r.selected).forEach(r => {
        r.promo_price = Math.max(0, Math.round(r.price * factor));
      });
      this.showDiscount = false;
    },

    applyDefaultStock() {
      this.rows.filter(r => r.selected).forEach(r => {
        r.stock = this.defaultStock;
      });
      this.showStock = false;
    },

    openRowFilePicker(row) {
      this.pendingUploadRow = row;
      this.$refs.rowFileInput.click();
    },

    async uploadRowImage(file) {
      const row = this.pendingUploadRow;
      this.pendingUploadRow = null;
      if (!file || !row) return;

      if (row.isNew) {
        // Produit pas encore cree : on garde la photo en memoire, elle
        // partira vers le serveur au moment de publish() une fois le
        // produit reellement cree (meme mecanisme que pour une photo
        // groupee sans correspondance, cf. handleFiles).
        row.pendingFile = file;
        row.image_url = URL.createObjectURL(file);
        return;
      }
      if (!row.product_id) return;

      const formData = new FormData();
      formData.append('file', file);
      formData.append('product_id', row.product_id);
      try {
        const res = await fetch(this.apiAssignImageUrl, {
          method: 'POST',
          headers: { 'X-CSRFToken': this.csrfToken() },
          body: formData,
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Erreur pendant l\'envoi de la photo.');
        row.image_url = data.url;
        this.setMessage('Photo mise a jour.', 'success');
      } catch (e) {
        this.setMessage(e.message, 'error');
      }
    },

    async handleFiles(fileList) {
      const files = Array.from(fileList || []);
      if (files.length === 0) return;
      this.uploadingCount = files.length;
      const formData = new FormData();
      files.forEach(f => formData.append('files', f));
      // Ordre des lignes actuellement affichees (produits deja crees
      // seulement -- une ligne "nouvelle" pas encore publiee n'a pas de
      // product_id et ne peut pas recevoir de photo pour l'instant) :
      // sert de filet de secours positionnel quand le nom du fichier ne
      // correspond a aucun produit (photos prises au telephone, non
      // renommees). Le vendeur depose ses photos dans le meme ordre que
      // ses lignes, aucun renommage requis.
      const productOrder = this.rows.filter(r => !r.isNew && r.product_id).map(r => r.product_id);
      formData.append('product_order', JSON.stringify(productOrder));
      try {
        const res = await fetch(this.apiBulkUploadUrl, {
          method: 'POST',
          headers: { 'X-CSRFToken': this.csrfToken() },
          body: formData,
        });
        const data = await res.json();
        let byPosition = 0;
        (data.uploads || []).forEach(u => {
          const row = this.rows.find(r => r.product_id === u.auto_assigned_product_id);
          if (row) row.image_url = u.url;
          if (u.match_kind === 'position') byPosition += 1;
        });

        // Photos sans correspondance (ni nom, ni ligne existante vide) :
        // plutot que de forcer un rattachement manuel, on cree directement
        // une ligne vide par photo, dans l'ordre de depot, avec la photo
        // deja en place (previsualisation locale). Le vendeur n'a plus qu'a
        // renseigner nom/prix/stock ; la photo part vers le serveur des que
        // la ligne est publiee (cf. publish()), une fois le produit cree.
        const unmatched = data.errors || [];
        const newRows = unmatched.map(err => {
          const file = files.find(f => f.name === err.filename);
          return {
            key: 'new' + Date.now() + Math.random(),
            isNew: true,
            product_id: null,
            name: '',
            price: 0,
            image_url: file ? URL.createObjectURL(file) : null,
            pendingFile: file || null,
            selected: true,
            promo_price: null,
            stock: 0,
            display_order: 0,
            isActive: true,
          };
        });
        if (newRows.length) {
          this.rows.splice(0, 0, ...newRows);
          this.refreshIcons();
        }

        const parts = [];
        if (data.uploads && data.uploads.length) {
          const positionNote = byPosition ? ` (dont ${byPosition} par ordre de dépôt)` : '';
          parts.push(`${data.uploads.length} photo(s) rattachée(s)${positionNote}`);
        }
        if (newRows.length) {
          parts.push(`${newRows.length} nouvelle(s) ligne(s) créée(s) avec photo à compléter`);
        }
        if (parts.length) {
          this.setMessage(parts.join(' · ') + '.', newRows.length && !data.uploads?.length ? 'warning' : 'success');
        }
      } catch (e) {
        this.setMessage("Erreur pendant l'envoi des photos.", 'error');
      } finally {
        this.uploadingCount = 0;
      }
    },

    async duplicateFrom() {
      if (!this.duplicateFromId) return;
      this.loading = true;
      try {
        const res = await fetch(this.apiDuplicateUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrfToken() },
          body: JSON.stringify({ previous_sale_id: this.duplicateFromId }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Erreur.');
        this.setMessage(`${data.duplicated_count} produit(s) repris.`, 'success');
        await this.loadCatalog();
      } catch (e) {
        this.setMessage(e.message, 'error');
      } finally {
        this.loading = false;
      }
    },

    async publish() {
      const selected = this.rows.filter(r => r.selected);
      if (selected.length === 0) return;
      this.loading = true;
      try {
        const mutations = selected.map(r => {
          const base = {
            promo_price: r.promo_price || null,
            display_order: r.display_order || 0,
            is_active: true,
          };
          if (r.isNew) {
            base.product_new = {
              name: r.name, price: r.price, stock: r.stock || 0, unit: 'piece',
            };
          } else {
            base.product_id = r.product_id;
            base.stock = r.stock;
          }
          return base;
        });

        const res = await fetch(this.apiBulkUpdateUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrfToken() },
          body: JSON.stringify({ mutations }),
        });
        const data = await res.json();
        if (!res.ok) {
          const detail = data.detail || 'Certaines lignes sont invalides.';
          this.setMessage(detail, 'error');
          return;
        }

        // Lignes creees a partir d'une photo groupee sans correspondance
        // (cf. handleFiles) : le produit vient d'etre cree par bulk-update
        // ci-dessus, on peut desormais lui envoyer la photo restee en
        // attente en memoire.
        const pendingUploads = selected
          .map((row, i) => ({ row, result: (data.results || [])[i] }))
          .filter(({ row, result }) => row.pendingFile && result);
        if (pendingUploads.length) {
          await Promise.all(pendingUploads.map(async ({ row, result }) => {
            const fd = new FormData();
            fd.append('file', row.pendingFile);
            fd.append('product_id', result.product_id);
            try {
              await fetch(this.apiAssignImageUrl, {
                method: 'POST',
                headers: { 'X-CSRFToken': this.csrfToken() },
                body: fd,
              });
            } catch (e) {
              // Publication deja actee cote produits/vente ; une photo en
              // echec ici reste corrigeable ensuite via le bouton photo en
              // ligne, pas la peine de bloquer la redirection pour ca.
            }
          }));
        }

        this.setMessage(`${data.created_count + data.updated_count} produit(s) publié(s).`, 'success');
        setTimeout(() => { window.location.href = this.saleDetailUrl; }, 900);
      } catch (e) {
        this.setMessage('Erreur pendant la publication.', 'error');
      } finally {
        this.loading = false;
      }
    },

    setMessage(text, type) {
      this.message = text;
      this.messageType = type;
      setTimeout(() => { this.message = ''; }, 6000);
    },
  };
}
