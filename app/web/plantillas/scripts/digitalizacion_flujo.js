/* Navegación progresiva: sin JavaScript, el formulario completo sigue disponible. */
(() => {
  'use strict';
  const raiz = document.getElementById('flujo-digitalizacion');
  if (!raiz) return;
  const identidad = document.getElementById('confirmar-identidad');
  const entrada = document.getElementById('imagenes-historicas');
  function ir(paso, enfocar = true) {
    if (paso === 3 && !identidad.checked) { identidad.reportValidity(); return; }
    raiz.querySelectorAll('[data-etapa]').forEach(panel => { panel.hidden = Number(panel.dataset.etapa) !== paso; });
    raiz.querySelectorAll('[data-indicador]').forEach(indicador => {
      if (Number(indicador.dataset.indicador) === paso) indicador.setAttribute('aria-current', 'step');
      else indicador.removeAttribute('aria-current');
    });
    const tarjeta = document.querySelector('[aria-labelledby="identidad-documentos"]');
    const acceso = document.getElementById('acceso-seguimiento');
    if (acceso) acceso.hidden = paso === 4 || paso === 1;
    if (tarjeta) tarjeta.hidden = paso === 1 || paso === 4;
    if (enfocar) raiz.querySelector(`[data-etapa="${paso}"] h2`)?.focus();
  }
  raiz.classList.add('dig-activo');
  raiz.querySelectorAll('[data-ir]').forEach(boton => boton.addEventListener('click', () => {
    if (boton.hasAttribute('data-nuevo-lote')) {
      identidad.checked = false;
      entrada.value = '';
      entrada.dispatchEvent(new Event('change'));
    }
    ir(Number(boton.dataset.ir));
  }));
  document.getElementById('confirmar-continuar')?.addEventListener('click', () => {
    if (identidad.reportValidity()) ir(3);
  });
  if (entrada) {
    const lista = document.getElementById('archivos-seleccionados');
    const resumen = document.getElementById('resumen-archivos');
    const zona = document.getElementById('zona-imagenes');
    function mostrarArchivos() {
      const archivos = [...entrada.files];
      const total = archivos.reduce((suma, archivo) => suma + archivo.size, 0);
      const error = archivos.length > 10 ? 'Selecciona hasta 10 archivos.' : archivos.some(a => a.size > 10 * 1024 * 1024) ? 'Cada archivo debe pesar como máximo 10 MB.' : total > 50 * 1024 * 1024 ? 'El lote no puede superar 50 MB.' : '';
      entrada.setCustomValidity(error);
      lista.replaceChildren();
      archivos.forEach((archivo, indice) => {
        const fila = document.createElement('li');
        const nombre = document.createElement('span');
        nombre.textContent = `${archivo.name} · ${(archivo.size / 1024 / 1024).toFixed(2)} MB`;
        fila.append(nombre);
        if (typeof DataTransfer !== 'undefined') {
          const quitar = document.createElement('button');
          quitar.type = 'button'; quitar.className = 'btn btn--neutral'; quitar.textContent = 'Quitar';
          quitar.setAttribute('aria-label', `Quitar ${archivo.name}`);
          quitar.addEventListener('click', () => {
            const transferencia = new DataTransfer();
            archivos.forEach((a, i) => { if (i !== indice) transferencia.items.add(a); });
            entrada.files = transferencia.files; mostrarArchivos();
          });
          fila.append(quitar);
        }
        lista.append(fila);
      });
      resumen.textContent = error || `${archivos.length} archivos · ${(total / 1024 / 1024).toFixed(2)} MB de 50 MB`;
    }
    entrada.addEventListener('change', mostrarArchivos);
    zona.addEventListener('dragover', evento => { evento.preventDefault(); zona.dataset.arrastrando = ''; });
    zona.addEventListener('dragleave', () => { delete zona.dataset.arrastrando; });
    zona.addEventListener('drop', evento => {
      evento.preventDefault(); delete zona.dataset.arrastrando;
      if (evento.dataTransfer.files.length) { entrada.files = evento.dataTransfer.files; mostrarArchivos(); }
    });
    entrada.form.addEventListener('submit', evento => {
      if (!identidad.checked) { evento.preventDefault(); ir(2); identidad.reportValidity(); }
    });
    // La validación nativa puede encontrar la confirmación en una etapa oculta.
    identidad.addEventListener('invalid', () => ir(2));
  }
  ir(Number(raiz.dataset.inicio), false);
})();
