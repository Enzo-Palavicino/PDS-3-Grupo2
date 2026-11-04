/* JS progresivo. Sin él, todo funciona igual: confirm() nativo y envío normal de formularios.
   1. Diálogo de confirmación propio para revocar y descartar (formularios con data-confirm-title):
      foco inicial en "Cancelar", Esc o clic fuera cierra, el foco vuelve al botón de origen y
      "Sí, …" envía el mismo POST con su CSRF.
   2. Estado "enviando" (formularios con data-enviando): texto en gerundio y aria-disabled, para
      evitar el doble envío sin deshabilitar el botón antes de que el navegador envíe. */
(function () {
  "use strict";

  var dialogo = document.getElementById("dialogo-confirmacion");
  var conDialogo = !!(dialogo && typeof dialogo.showModal === "function");
  var pendiente = null; // formulario y botón que abrieron el diálogo

  function botonDe(formulario) {
    return formulario.querySelector('button[type="submit"], button:not([type])');
  }

  function marcarEnviando(formulario) {
    var boton = botonDe(formulario);
    if (!boton || boton.getAttribute("aria-disabled") === "true") return;
    var etiqueta = boton.querySelector(".btn__label");
    if (etiqueta && formulario.dataset.enviando) {
      boton.dataset.textoOriginal = etiqueta.innerHTML;
      etiqueta.textContent = formulario.dataset.enviando;
    }
    var icono = boton.querySelector(".icon");
    if (icono) icono.style.display = "none";
    var giro = document.createElement("span");
    giro.className = "btn__spinner";
    giro.setAttribute("aria-hidden", "true");
    boton.insertBefore(giro, boton.firstChild);
    boton.setAttribute("aria-disabled", "true");
    formulario.dataset.enviado = "1";
  }

  function restaurar(formulario) {
    var boton = botonDe(formulario);
    delete formulario.dataset.enviado;
    delete formulario.dataset.confirmado;
    if (!boton) return;
    var etiqueta = boton.querySelector(".btn__label");
    if (etiqueta && boton.dataset.textoOriginal !== undefined) etiqueta.innerHTML = boton.dataset.textoOriginal;
    var giro = boton.querySelector(".btn__spinner");
    if (giro) giro.remove();
    var icono = boton.querySelector(".icon");
    if (icono) icono.style.display = "";
    boton.removeAttribute("aria-disabled");
  }

  function abrirDialogo(formulario, boton) {
    pendiente = { formulario: formulario, boton: boton || botonDe(formulario) };
    dialogo.querySelector(".dialog__title").textContent = formulario.dataset.confirmTitle;
    dialogo.querySelector(".dialog__body").textContent = formulario.dataset.confirmBody || "";
    dialogo.querySelector('[value="confirmar"]').textContent = formulario.dataset.confirmLabel || "Confirmar";
    dialogo.returnValue = "";
    dialogo.showModal();
    dialogo.querySelector('[value="cancelar"]').focus();
  }

  if (conDialogo) {
    // El diálogo reemplaza al confirm() nativo, que queda solo como respaldo sin JS.
    document.querySelectorAll("form[data-confirm-title]").forEach(function (formulario) {
      formulario.removeAttribute("onsubmit");
    });

    dialogo.addEventListener("click", function (evento) {
      if (evento.target === dialogo) dialogo.close(); // clic en el fondo
    });

    dialogo.addEventListener("close", function () {
      if (!pendiente) return;
      var datos = pendiente;
      pendiente = null;
      if (dialogo.returnValue === "confirmar") {
        datos.formulario.dataset.confirmado = "1";
        if (typeof datos.formulario.requestSubmit === "function") {
          datos.formulario.requestSubmit(datos.boton || undefined);
        } else {
          marcarEnviando(datos.formulario);
          datos.formulario.submit();
        }
      } else if (datos.boton) {
        datos.boton.focus();
      }
    });
  }

  document.addEventListener("submit", function (evento) {
    var formulario = evento.target;
    if (!(formulario instanceof HTMLFormElement) || formulario.method === "dialog") return;
    if (formulario.dataset.enviado === "1") {
      evento.preventDefault(); // doble envío
      return;
    }
    if (conDialogo && formulario.dataset.confirmTitle && formulario.dataset.confirmado !== "1") {
      evento.preventDefault();
      abrirDialogo(formulario, evento.submitter);
      return;
    }
    if (evento.defaultPrevented) return; // el usuario canceló el confirm() nativo
    if (formulario.dataset.enviando) marcarEnviando(formulario);
  });

  // Al volver con "atrás" el navegador puede restaurar la página tal como quedó: se reactivan
  // los botones que estaban en "enviando".
  window.addEventListener("pageshow", function (evento) {
    if (!evento.persisted) return;
    document.querySelectorAll("form[data-enviado]").forEach(restaurar);
  });
})();
