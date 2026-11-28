/*
 * Formato y validación del RUT en el navegador (frontend).
 * Se aplica a todo <input data-rut>. El servidor vuelve a validar (backend).
 *  - Mientras se escribe: deja solo números y K, y formatea 12.345.678-5.
 *  - Al salir del campo: revisa el dígito verificador y avisa si no corresponde.
 */
(function () {
  "use strict";

  function limpiar(valor) {
    return (valor || "").toUpperCase().replace(/[^0-9K]/g, "").replace(/K(?=.)/g, "");
  }

  function formatear(valor) {
    var limpio = limpiar(valor).slice(0, 9);
    if (limpio.length < 2) return limpio;
    var cuerpo = limpio.slice(0, -1).replace(/^0+/, "");
    var dv = limpio.slice(-1);
    return cuerpo.replace(/\B(?=(\d{3})+(?!\d))/g, ".") + "-" + dv;
  }

  function digitoVerificador(cuerpo) {
    var suma = 0, multiplicador = 2;
    for (var i = cuerpo.length - 1; i >= 0; i--) {
      suma += parseInt(cuerpo.charAt(i), 10) * multiplicador;
      multiplicador = multiplicador === 7 ? 2 : multiplicador + 1;
    }
    var resto = 11 - (suma % 11);
    return resto === 11 ? "0" : resto === 10 ? "K" : String(resto);
  }

  function esValido(valor) {
    var limpio = limpiar(valor);
    if (limpio.length < 2) return false;
    var cuerpo = limpio.slice(0, -1);
    if (!/^\d+$/.test(cuerpo) || parseInt(cuerpo, 10) < 1000000) return false;
    return digitoVerificador(cuerpo) === limpio.slice(-1);
  }

  function revisar(input) {
    if (!input.value) {
      input.setCustomValidity("");
      return;
    }
    input.setCustomValidity(
      esValido(input.value) ? "" : "RUT inválido: revisa los números y el dígito verificador."
    );
  }

  document.querySelectorAll("input[data-rut]").forEach(function (input) {
    input.setAttribute("maxlength", "12");
    if (input.value) input.value = formatear(input.value);
    input.addEventListener("input", function () {
      input.value = formatear(input.value);
      input.setCustomValidity("");
    });
    input.addEventListener("blur", function () {
      revisar(input);
      if (input.validationMessage) input.reportValidity();
    });
  });

  window.AylluRut = { formatear: formatear, esValido: esValido };
})();
