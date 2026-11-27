const botonMenu = document.querySelector('.abrir-menu');
const secciones = document.getElementById('secciones-club');
const movil = window.matchMedia('(max-width: 760px)');

function adaptarMenu() {
  botonMenu.hidden = !movil.matches;
  botonMenu.setAttribute('aria-expanded', 'false');
  secciones.hidden = movil.matches;
}

botonMenu.addEventListener('click', () => {
  secciones.hidden = !secciones.hidden;
  botonMenu.setAttribute('aria-expanded', String(!secciones.hidden));
});
movil.addEventListener('change', adaptarMenu);
adaptarMenu();
