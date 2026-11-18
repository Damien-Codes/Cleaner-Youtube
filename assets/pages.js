/*
 * Script des pages secondaires (ex. confidentialite.html) : ouverture et fermeture
 * des modales du pied de page (« Conditions d'utilisation », « Licence MIT »).
 */
(() => {
  "use strict";
  function bindDialogs() {
    document.querySelectorAll("[data-dialog]").forEach(btn => btn.addEventListener("click", () => {
      const d = document.getElementById(btn.dataset.dialog);
      if (d && typeof d.showModal === "function") d.showModal();
    }));
    document.querySelectorAll("dialog.modal").forEach(d => {
      d.addEventListener("click", e => {
        // Fermeture : bouton × ou clic sur le fond (en dehors du contenu).
        if (e.target.closest("[data-close]") || e.target === d) d.close();
      });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bindDialogs);
  else bindDialogs();
})();
