(() => {
  "use strict";
  const formulario = document.getElementById("revision-documento");
  if (!formulario) return;
  formulario.querySelectorAll(".dig-agregar, .dig-quitar").forEach(boton => { boton.hidden = false; });
  formulario.addEventListener("click", evento => {
    const boton = evento.target.closest("button");
    if (!boton) return;
    if (boton.classList.contains("dig-quitar")) {
      const fila = boton.closest(".dig-fila");
      fila.querySelectorAll("input, textarea").forEach(campo => { campo.value = ""; });
      // Conserva las posiciones para no asociar otro dato a un fragmento equivocado.
      fila.hidden = true;
    }
    if (boton.classList.contains("dig-agregar")) {
      const filas = boton.closest(".dig-grupo").querySelector(".dig-filas");
      const nueva = filas.querySelector(".dig-fila").cloneNode(true);
      nueva.hidden = false;
      nueva.querySelectorAll("input, textarea").forEach(campo => { campo.value = ""; });
      const evidencia = nueva.querySelector(".dig-evidencia");
      evidencia.textContent = "Añadido en la revisión; sin fragmento de la IA.";
      evidencia.classList.remove("dig-ilegible");
      filas.appendChild(nueva);
      nueva.querySelector("input, textarea").focus();
    }
  });
})();
