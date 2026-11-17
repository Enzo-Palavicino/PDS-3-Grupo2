/* Seguimiento de la cola; nunca inicia ni simula procesamiento de documentos. */
(() => {
  "use strict";
  const seccion = document.querySelector('[data-documentos-residente]');
  if (!seccion) return;
  const tbody = document.getElementById('filas-documentos');
  const aviso = document.getElementById('actualizacion-documentos');
  const enlace = document.getElementById('actualizar-documentos');
  let temporizador, ocupado = false, detenido = false;
  const controlador = new AbortController();

  function mostrar(documentos) {
    const ids = new Set(documentos.map(d => String(d.id)));
    tbody.querySelectorAll('[data-documento-id]').forEach(fila => {
      if (!ids.has(fila.dataset.documentoId)) fila.remove();
    });
    if (documentos.length) tbody.querySelector('[data-vacio]')?.remove();
    [...documentos].reverse().forEach(d => {
      let fila = tbody.querySelector(`[data-documento-id="${Number(d.id)}"]`);
      if (!fila) {
        fila = document.createElement('tr');
        fila.dataset.documentoId = String(Number(d.id));
        for (let i = 0; i < 6; i++) {
          const celda = document.createElement(i === 0 ? 'th' : 'td');
          if (i === 0) celda.scope = 'row';
          fila.appendChild(celda);
        }
        const descargar = document.createElement('a');
        descargar.textContent = 'Descargar original';
        fila.children[5].appendChild(descargar);
        tbody.prepend(fila);
      }
      [d.nombre, d.tipo, d.fecha, d.estado, d.intentos].forEach((valor, i) => {
        const texto = String(valor);
        if (fila.children[i].textContent !== texto) fila.children[i].textContent = texto;
      });
      fila.children[5].querySelector('a').href = `/adjuntos/${Number(d.adjunto_id)}/descargar`;
    });
    if (!documentos.length && !tbody.querySelector('[data-vacio]')) {
      const fila = document.createElement('tr');
      fila.dataset.vacio = '';
      const celda = document.createElement('td');
      celda.colSpan = 6;
      celda.textContent = 'Todavía no hay documentos históricos para este residente.';
      fila.appendChild(celda);
      tbody.appendChild(fila);
    }
  }

  async function actualizar() {
    if (ocupado || detenido) return;
    clearTimeout(temporizador);
    if (document.hidden) {
      temporizador = setTimeout(actualizar, 5000);
      return;
    }
    ocupado = true;
    try {
      const respuesta = await fetch(`/digitalizacion/estados?residente_id=${encodeURIComponent(seccion.dataset.documentosResidente)}`, {
        credentials: 'same-origin', cache: 'no-store', signal: controlador.signal,
        headers: { Accept: 'application/json' }
      });
      if (respuesta.redirected || respuesta.status === 401 || respuesta.status === 403) {
        detenido = true;
        aviso.textContent = 'La sesión o el permiso cambiaron. Vuelve a iniciar sesión para consultar los estados.';
        return;
      }
      if (!respuesta.ok) throw new Error('respuesta');
      const datos = await respuesta.json();
      if (!Array.isArray(datos.documentos)) throw new Error('formato');
      mostrar(datos.documentos);
      aviso.textContent = 'Estados actualizados. Se volverán a consultar automáticamente.';
    } catch (error) {
      if (!detenido) aviso.textContent = 'No se pudo actualizar. Se reintentará automáticamente; los documentos guardados se conservan.';
    } finally {
      ocupado = false;
      if (!detenido) temporizador = setTimeout(actualizar, 5000);
    }
  }
  enlace.addEventListener('click', evento => {
    if (!detenido) { evento.preventDefault(); actualizar(); }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) actualizar(); });
  window.addEventListener('pagehide', () => {
    detenido = true; clearTimeout(temporizador); controlador.abort();
  });
  temporizador = setTimeout(actualizar, 5000);
})();
