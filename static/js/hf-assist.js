/* Saisie assistee (staff) : une photo = un bloc produit, champs empiles.
 * Les photos sont reduites (1600 px, JPEG) avant l'envoi pour rester sous la
 * limite Nginx (10 Mo par requete). Aucun script inline (CSP). */
(function () {
  'use strict';
  var form = document.querySelector('[data-hf-assist-form]');
  if (!form) return;

  var input = form.querySelector('[data-hf-assist-photos]');
  var list = form.querySelector('[data-hf-assist-rows]');
  var countField = form.querySelector('[data-hf-assist-count]');
  var errorBox = form.querySelector('[data-hf-assist-error]');
  var submitBtn = form.querySelector('[data-hf-assist-submit]');
  var tpl = document.querySelector('[data-hf-assist-template]');
  var max = parseInt(form.dataset.hfAssistMax || '20', 10);
  var MAX_BYTES = 9 * 1024 * 1024;
  var items = []; // {file, node}

  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.hidden = !msg;
  }

  function renumber() {
    items.forEach(function (it, i) {
      it.node.querySelector('[data-hf-assist-title]').textContent = 'Produit ' + (i + 1);
    });
    countField.value = String(items.length);
  }

  function addFile(file) {
    var node = tpl.content.firstElementChild.cloneNode(true);
    var img = node.querySelector('[data-hf-assist-preview]');
    img.src = URL.createObjectURL(file);
    var item = { file: file, node: node };
    node.querySelector('[data-hf-assist-remove]').addEventListener('click', function () {
      items = items.filter(function (x) { return x !== item; });
      node.remove();
      renumber();
    });
    items.push(item);
    list.appendChild(node);
  }

  input.addEventListener('change', function () {
    showError('');
    var files = Array.prototype.slice.call(input.files || []);
    if (items.length + files.length > max) {
      showError(max + ' produits maximum par envoi : envoie le reste en une 2e fois.');
      files = files.slice(0, Math.max(0, max - items.length));
    }
    files.forEach(addFile);
    renumber();
    input.value = '';
    var first = items.length ? items[items.length - files.length] : null;
    if (first) first.node.querySelector('[data-field="name"]').focus();
  });

  function shrink(file) {
    return new Promise(function (resolve) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        var scale = Math.min(1, 1600 / Math.max(img.width, img.height));
        var canvas = document.createElement('canvas');
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);
        canvas.toBlob(function (blob) {
          resolve(blob && blob.size < file.size ? blob : file);
        }, 'image/jpeg', 0.82);
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolve(file); };
      img.src = url;
    });
  }

  form.addEventListener('submit', function (ev) {
    ev.preventDefault();
    showError('');
    if (!items.length) { showError('Sélectionne au moins une photo.'); return; }
    if (!form.reportValidity()) return;

    submitBtn.disabled = true;
    submitBtn.textContent = 'Envoi en cours…';
    var data = new FormData();
    data.append('csrfmiddlewaretoken', form.querySelector('[name=csrfmiddlewaretoken]').value);
    data.append('whatsapp_ref', form.querySelector('[name=whatsapp_ref]').value);
    data.append('count', String(items.length));
    items.forEach(function (it, i) {
      it.node.querySelectorAll('[data-field]').forEach(function (f) {
        data.append(f.dataset.field + '_' + i, f.value);
      });
    });

    Promise.all(items.map(function (it) { return shrink(it.file); })).then(function (blobs) {
      var total = 0;
      blobs.forEach(function (b, i) {
        total += b.size;
        data.append('photos', b, 'produit-' + (i + 1) + '.jpg');
      });
      if (total > MAX_BYTES) {
        throw new Error('Photos trop lourdes pour un seul envoi : retire quelques produits et envoie-les en une 2e fois.');
      }
      return fetch(form.action || window.location.href, {
        method: 'POST', body: data, credentials: 'same-origin'
      });
    }).then(function (res) {
      if (res.redirected) { window.location.href = res.url; return; }
      if (res.status === 413) {
        throw new Error('Envoi trop lourd : envoie les produits en deux fois.');
      }
      return res.text().then(function (html) {
        document.open(); document.write(html); document.close();
      });
    }).catch(function (err) {
      showError(err && err.message ? err.message : 'Envoi impossible. Vérifie la connexion et réessaie.');
      submitBtn.disabled = false;
      submitBtn.textContent = 'Enregistrer les produits';
    });
  });
})();
