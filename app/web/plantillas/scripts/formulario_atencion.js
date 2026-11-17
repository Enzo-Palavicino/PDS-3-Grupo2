/* "Agregar indicación": suma otra fila de indicación farmacológica. Sin JavaScript, el
   formulario trae dos filas vacías y se puede guardar igual. */
(() => {
  "use strict";
  const contenedor = document.querySelector("[data-indicaciones]");
  const plantilla = document.querySelector("[data-plantilla-indicacion]");
  const boton = document.querySelector("[data-agregar-indicacion]");
  if (!contenedor || !plantilla || !boton) return;
  boton.hidden = false;
  boton.addEventListener("click", () => {
    const numero = contenedor.querySelectorAll("[data-indicacion]").length + 1;
    const fila = plantilla.content.firstElementChild.cloneNode(true);
    fila.querySelector("[data-numero]").textContent = String(numero);
    fila.querySelectorAll("[id], [for]").forEach((elemento) => {
      ["id", "for"].forEach((atributo) => {
        const valor = elemento.getAttribute(atributo);
        if (valor) elemento.setAttribute(atributo, valor.replace("__N__", String(numero)));
      });
    });
    contenedor.appendChild(fila);
    fila.querySelector("input")?.focus();
  });
})();
