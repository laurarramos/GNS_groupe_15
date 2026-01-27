# GNS_groupe_15

Ce projet automatise la configuration d'un réseau IPv6 complet. La topologie est générée dynamiquement à partir d'un fichier JSON. L'objectif est de déployer automatiquement un réseau opérateur fonctionnel, incluant le routage interne (IGP) et les politiques de routage externe (BGP).

## Fonctionnalités Principales

* **Dual IGP** : Support de **RIPng** et **OSPFv3** pour le routage interne selon les AS.
* **Routage BGP Avancé** :
    * Sessions eBGP (Inter-AS) et iBGP (Intra-AS).
    * Utilisation de **Route Reflectors** pour la scalabilité iBGP.
    * Politique de **Next-Hop-Self** sur les bordures pour la cohérence interne.
* **Ingénierie de Trafic** :
    * Application des relations **Gao-Rexford** (Client / Peer / Provider).
    * Manipulation des **Communautés BGP** et de la **Local Preference**.
* **Optimisation globale** : Agrégation de préfixes (`aggregate-address summary-only`) pour la stabilité du réseau.

---

## Architecture du Code Python

1. **Couche IGP** : Adressage des interfaces et activation du protocole interne (RIP/OSPF).
2. **Couche BGP** : Mise en place du plan de contrôle (Voisinages, Route Reflectors).
3. **Couche Policy** : Création des **Route-maps** en mode global et application dans l'**Address-Family IPv6**.
4. **Convergence** : Envoi d'un `clear bgp ipv6 unicast * soft` pour appliquer les politiques sans coupure de session.

---

## Concepts Clés Implémentés

### 1. Politique d'Export & Communautés
Nous avons implémenté une politique stricte : **un AS ne transite que les routes de ses clients**. 
Pour que l'AS local soit joignable, le script utilise une route-map de redistribution qui tague les préfixes internes avec la communauté `CLIENT` (ex: `65001:100`). Cela permet aux filtres de sortie (`OUT-PROVIDER`) d'autoriser l'annonce de nos propres réseaux tout en bloquant le transit non-désiré entre fournisseurs.

### 2. Agrégation de Routes (`Aggregate-Policy`)
Pour protéger la table de routage mondiale, nous agrégons les préfixes `/64` internes en un seul préfixe `/48` par AS.
* **Summary-only** : Masque les détails internes pour n'afficher que la route globale aux voisins eBGP.
* **Stabilité** : Évite le "Route Flapping" (si un lien interne `/64` tombe, l'agrégat externe `/48` reste annoncé, évitant des recalculs BGP mondiaux).

---

## Installation & Utilisation
1. Lancer la structure vide dans **GNS3** et démarrer les nodes.
2. Exécuter le script : `python main.py`.
