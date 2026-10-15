// Comportamiento común a todas las páginas. Sin dependencias; todo es mejora progresiva:
// si este archivo no carga, los formularios siguen funcionando igual.
(function () {
  var CLAVE = 'tras-guardar';

  // ── Tras enviar un formulario la página se recarga entera: se vuelve al mismo punto
  //    de scroll y se confirma con un aviso breve, en vez de saltar arriba sin decir nada.
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (e.defaultPrevented || (form.method || '').toLowerCase() !== 'post') return;
    var boton = e.submitter || form.querySelector('button[type="submit"]');
    try {
      sessionStorage.setItem(CLAVE, JSON.stringify({
        ruta: location.pathname,
        y: window.scrollY,
        aviso: form.dataset.aviso || 'Guardado',
      }));
    } catch (err) { /* sin sessionStorage no hay aviso, nada más */ }
    if (boton) {
      // Tras el envío, para no cancelar el propio submit ni perder el valor del botón.
      setTimeout(function () {
        boton.disabled = true;
        if (form.dataset.enviando) boton.textContent = form.dataset.enviando;
      }, 0);
    }
  });

  function aviso(texto) {
    var el = document.createElement('div');
    el.className = 'toast';
    el.setAttribute('role', 'status');
    el.textContent = texto;
    document.body.appendChild(el);
    setTimeout(function () { el.classList.add('fuera'); }, 2200);
    setTimeout(function () { el.remove(); }, 2700);
  }

  var pendiente = null;
  try {
    pendiente = JSON.parse(sessionStorage.getItem(CLAVE));
    sessionStorage.removeItem(CLAVE);
  } catch (err) { /* nada */ }
  if (pendiente && pendiente.ruta === location.pathname) {
    window.scrollTo(0, pendiente.y);
    aviso(pendiente.aviso);
  }

  // ── Importes editables en la propia fila: "Guardar" solo aparece al cambiar el valor.
  document.querySelectorAll('.solo-si-cambia input[type="number"]').forEach(function (input) {
    input.addEventListener('input', function () {
      input.form.classList.toggle('cambiado', input.value !== input.defaultValue);
    });
  });

  // ── Filtros que se aplican solos al elegir (sin botón "Filtrar").
  document.querySelectorAll('form[data-autoenviar] select').forEach(function (sel) {
    sel.addEventListener('change', function () { sel.form.submit(); });
  });

  // ── Buscador que filtra bloques de la página: <input data-filtra=".selector">.
  //    Un bloque se ve si su texto (o data-texto) contiene todo lo escrito.
  var norm = function (s) { return s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); };
  document.querySelectorAll('input[data-filtra]').forEach(function (input) {
    var bloques = Array.from(document.querySelectorAll(input.dataset.filtra));
    var textos = bloques.map(function (b) { return norm(b.dataset.texto || b.textContent); });
    var vacio = document.querySelector(input.dataset.vacio || '#sin-resultados');
    input.addEventListener('input', function () {
      var palabras = norm(input.value).split(/\s+/).filter(Boolean);
      var visibles = 0;
      bloques.forEach(function (b, i) {
        var ok = palabras.every(function (p) { return textos[i].includes(p); });
        b.hidden = !ok;
        if (ok) visibles++;
        // Buscando, los bloques plegables que coinciden se abren para ver la regla.
        if (b.tagName === 'DETAILS') b.open = ok && palabras.length > 0;
      });
      if (vacio) vacio.hidden = visibles > 0;
    });
  });
})();
