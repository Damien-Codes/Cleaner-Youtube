/*
 * Configuration du site statique Cleaner YouTube.
 *
 * GOOGLE_CLIENT_ID : ID client OAuth 2.0 de type « Application Web » créé dans Google Cloud Console.
 * Un ID client n'est pas un secret : il peut être publié dans le dépôt.
 * Ne mettez JAMAIS de « client secret » dans ce fichier.
 *
 * Si vous forkez le projet, remplacez cette valeur par l'ID client de votre propre projet Google Cloud.
 */
const GOOGLE_CLIENT_ID = "344055175331-3k0t72s0mp2e59d706s4pgp1gfthc16k.apps.googleusercontent.com";

// Exposé explicitement sur window : lisible par assets/app.js quel que soit le contexte de chargement.
window.GOOGLE_CLIENT_ID = GOOGLE_CLIENT_ID;
