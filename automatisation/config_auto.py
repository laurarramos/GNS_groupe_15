import os
import json
import time
import telnetlib
from ipaddress import IPv6Network

from collections import defaultdict

from gns3fy import Gns3Connector, Project, Node

# --- IMPORTANT: éviter que le proxy INSA (Squid) intercepte l'API locale GNS3 ---
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

GNS3_URL = "http://127.0.0.1:3080"
OSPF_PROCESS_ID = 1
DEFAULT_OSPF_AREA = 0
TELNET_DELAY = 0.3

# Route Reflectors par AS
RR_BY_AS = {
    "X": ["X3", "X4"],
    "Y": ["Y3", "Y6"],
}


with open("intent.json", "r", encoding="utf-8") as f:
    intent = json.load(f)

server = Gns3Connector(url=GNS3_URL)
project = Project(name="structure_vide", connector=server)
project.get()
project.open()
project.get_nodes()

# ---------------------- Utils Telnet & IP helpers ----------------------

def send(tn, cmd: str, delay: float = TELNET_DELAY):
    """
    Envoie une commande CLI via Telnet avec temporisation.
    Args:
        tn (telnetlib.Telnet): Session Telnet active.
        cmd (str): Commande à envoyer.
        delay (float): Délai après envoi en secondes.
    Returns:
        None
    """
    tn.write((cmd + "\r\n").encode("ascii", errors="ignore"))
    time.sleep(delay)

def iface_addr(prefix: str, host_id: int) -> str:
    """
    Construit une adresse IPv6 hôte à partir d’un préfixe.
    Args:
        prefix (str): Préfixe IPv6 (ex: "2001:db8:100:0::/64").
        host_id (int): Identifiant hôte à ajouter (ex: 1, 2, ...).
    Returns:
        str: Adresse IPv6 au format "addr/prefixlen".
    """
    net = IPv6Network(prefix, strict=False)
    return f"{net.network_address + host_id}/{net.prefixlen}"

def ensure_node_started(node: Node, wait_s: float = 2.0):
    """
    Démarre un node GNS3 s’il n’est pas déjà lancé.
    Args:
        node (Node): Node GNS3 à vérifier.
        wait_s (float): Temps d’attente après démarrage.
    Returns:
        None
    """
    node.get()
    if node.status != "started":
        node.start()
        time.sleep(wait_s)
        node.get()

def prefix64_from_48(net48: str, link_id: int) -> str:
    """
    Génère un préfixe IPv6 /64 à partir d’un /48 et d’un link_id.
    Args:
        net48 (str): Réseau IPv6 /48.
        link_id (int): Identifiant de lien.
    Returns:
        str: Préfixe IPv6 /64.
    """
    n48 = IPv6Network(net48, strict=False)
    base = int(n48.network_address)

    # Le subnet-id (/64) correspond aux 16 bits entre /48 et /64.
    # On place link_id dans ces 16 bits => décalage de 64 bits.
    addr64 = base + (int(link_id) << 64)
    n64 = IPv6Network((addr64, 64))
    return f"{n64.network_address}/{n64.prefixlen}"

def loopback_from_as48(as48: str, idx: int) -> str:
    """
    Génère une adresse IPv6 /128 de loopback à partir du /48 d’un AS.
    Args:
        as48 (str): Réseau IPv6 /48 de l’AS.
        idx (int): Index du routeur.
    Returns:
        str: Adresse IPv6 /128.
    """
    net48 = IPv6Network(as48, strict=False)
    base = int(net48.network_address)

    addr = base + (0xFFFF << 64) + int(idx)
    n128 = IPv6Network((addr, 128))
    return f"{n128.network_address}/{n128.prefixlen}"

def relation_between(as_local: str, as_remote: str) -> str:
    """
    Détermine la relation BGP entre deux AS du point de vue local.
    Args:
        as_local (str): AS local.
        as_remote (str): AS distant.
    Returns:
        str: Relation ('CLIENT', 'PROVIDER', 'PEER', 'UNKNOWN').
    """
    if as_remote in intent["AS"][as_local].get("providers", []):
        return "PROVIDER"
    if as_remote in intent["AS"][as_local].get("customers", []):
        return "CLIENT"
    if as_remote in intent["AS"][as_local].get("peers", []):
        return "PEER"
    return "UNKNOWN"


# ---------------------- Topology helpers ----------------------

def build_neighbors(intent_dict):
    """
    Construit la liste des voisins de chaque routeur.
    Args:
        intent_dict (dict): Intent réseau.
    Returns:
        dict: Dictionnaire routeur → voisins.
    """
    neigh = {r: [] for r in intent_dict["routeurs"].keys()}
    for link in intent_dict["links"]:
        a, b = link["routeur_a"], link["routeur_b"]
        neigh[a].append(b)
        neigh[b].append(a)
    return neigh

def is_border(router: str, intent_dict, neigh):
    '''
    Détermine si un routeur est une bordure inter-AS.

    Args:
        - router (str): nom du routeur
        - intent_dict (dict): dictionnaire de l'intent
        - neigh (dict): dictionnaire des voisins construit avec build_neighbors()
    
    Returns:
        - bool: True si bordure inter-AS, False sinon
    '''
    as_r = intent_dict["routeurs"][router]["as"]
    return any(intent_dict["routeurs"][v]["as"] != as_r for v in neigh[router])

def get_link(router_a: str, router_b: str, links):
    """
    Recherche le lien reliant deux routeurs.
    Args:
        router_a (str): Premier routeur.
        router_b (str): Second routeur.
        links (list): Liste des liens.
    Returns:
        dict | None: Lien correspondant ou None.
    """
    for link in links:
        a, b = link["routeur_a"], link["routeur_b"]
        if (a == router_a and b == router_b) or (a == router_b and b == router_a):
            return link
    return None


# ---------------------- IGP configs ----------------------

def config_RIP(node: Node, router_name: str, as_routeur: str):
    """
    Configure RIPng et les interfaces IPv6 d’un routeur.
    Args:
        node (Node): Node GNS3.
        router_name (str): Nom du routeur.
        as_routeur (str): AS du routeur.
    Returns:
        None
    """
    tn = telnetlib.Telnet(node.console_host, node.console)
    time.sleep(1)
    send(tn, "")

    # Début des commandes :
    send(tn, "enable")
    send(tn, "configure terminal")
    send(tn, "ipv6 unicast-routing")

    nom_process = intent["AS"][as_routeur]["nom_process"]
    send(tn, f"ipv6 router rip {nom_process}")
    send(tn, "exit")

    # Loopback
    idx = intent["routeurs"][router_name]["index"]
    as48 = intent["AS"][as_routeur]["network"]
    loopback_address = loopback_from_as48(as48, idx)
    send(tn, "interface Loopback0")
    send(tn, "ipv6 enable")
    send(tn, f"ipv6 address {loopback_address}")
    send(tn, f"ipv6 rip {nom_process} enable")
    send(tn, "exit")

    # Liens
    for link in intent["links"]:
        if router_name == link["routeur_a"]:
            voisin = link["routeur_b"]
            iface = link["interface_a"]
            host_id = 1
        elif router_name == link["routeur_b"]:
            voisin = link["routeur_a"]
            iface = link["interface_b"]
            host_id = 2
        else:
            continue

        #Choix du /48 à utiliser (intra-AS ou transit)
        if link.get("transit", False):
            net48 = intent["transit"]["network"]
        else:
            net48 = intent["AS"][as_routeur]["network"]

        #Construit le /64 depuis link_id
        prefix64 = prefix64_from_48(net48, link["link_id"])

        #Construit l'IP d'interface
        ip = iface_addr(prefix64, host_id)

        send(tn, f"interface {iface}")
        send(tn, "ipv6 enable")
        send(tn, f"ipv6 address {ip}")

        if intent["routeurs"][voisin]["as"] == as_routeur:
            send(tn, f"ipv6 rip {nom_process} enable")
        send(tn, "no shutdown")
        send(tn, "exit")

    send(tn, "end")
    time.sleep(1)
    send(tn, "write memory",delay=0.5)
    send(tn, "", delay=1) #au cas où
    tn.close()


def config_OSPF(node: Node, router_name: str, as_routeur: str, process_id: int = OSPF_PROCESS_ID, area: int = DEFAULT_OSPF_AREA):
    """
    Configure OSPFv3 et les interfaces IPv6 d’un routeur.
    Args:
        node (Node): Node GNS3.
        router_name (str): Nom du routeur.
        as_routeur (str): AS du routeur.
        process_id (int): ID du process OSPF.
        area (int): Aire OSPF.
    Returns:
        None
    """
    tn = telnetlib.Telnet(node.console_host, node.console)
    time.sleep(1)
    send(tn, "")
    
    #Début des commandes :
    send(tn, "enable")
    send(tn, "configure terminal")
    send(tn, "ipv6 unicast-routing")

    #routeur ID :
    send(tn, f"ipv6 router ospf {process_id}")
    routeurID = intent["routeurs"][router_name].get("routeurID")
    send(tn, f"router-id {routeurID}")
    send(tn, "exit")

    #loopback :
    idx = intent["routeurs"][router_name]["index"]
    as48 = intent["AS"][as_routeur]["network"]
    loopback_address = loopback_from_as48(as48, idx)
    send(tn, "interface Loopback0")
    send(tn, "ipv6 enable")
    send(tn, f"ipv6 address {loopback_address}")
    send(tn, f"ipv6 ospf {process_id} area {area}")
    send(tn, "exit")

    #liens avec voisins :
    for link in intent["links"]:
        if router_name == link["routeur_a"]:
            voisin = link["routeur_b"]
            iface = link["interface_a"]
            host_id = 1
        elif router_name == link["routeur_b"]:
            voisin = link["routeur_a"]
            iface = link["interface_b"]
            host_id = 2
        else:
            continue

        #Choix du /48 à utiliser (intra-AS ou transit)
        if link.get("transit", False):  
            net48 = intent["transit"]["network"]    
        else:
            net48 = intent["AS"][as_routeur]["network"]
        
        #Construit le /64 depuis link_id
        prefix64 = prefix64_from_48(net48, link["link_id"]) 

        #Construit l'IP d'interface
        ip = iface_addr(prefix64, host_id)

        send(tn, f"interface {iface}")
        send(tn, "ipv6 enable")
        send(tn, f"ipv6 address {ip}")

        if intent["routeurs"][voisin].get("as") == as_routeur:
            send(tn, f"ipv6 ospf {process_id} area {area}")
            #OSPF Metric
            cost = link.get("ospf_cost")
            if cost is not None:
                send(tn, f"ipv6 ospf cost {int(cost)}")
        send(tn, "no shutdown")
        send(tn, "exit")

    send(tn, "end")
    time.sleep(1)
    send(tn, "write memory",delay=0.5)
    send(tn, "", delay=1)
    tn.close()

# ---------------------- BGP config ----------------------

def config_BGP(node: Node, router_name: str, neigh):
    as_r = intent["routeurs"][router_name]["as"]
    border = is_border(router_name, intent, neigh)

    tn = telnetlib.Telnet(node.console_host, node.console)
    time.sleep(1)
    send(tn, "")
    send(tn, "enable")
    send(tn, "conf t")

    asn = int(intent["AS"][as_r]["asnumber"])
    rid = intent["routeurs"][router_name]["routeurID"]
    send(tn, f"router bgp {asn}")
    send(tn, f"bgp router-id {rid}")
    send(tn, "bgp log-neighbor-changes")

    # eBGP: voisins inter-AS (sur IP de lien)
    ebgp_peers = []
    if border:
        for v in neigh[router_name]:
            as_v = intent["routeurs"][v]["as"]
            if as_v == as_r:
                continue

            link=get_link(router_name, v, intent["links"])
            if not link:
                continue

            if not link.get("transit", False):
                continue

            transit_48 = intent["transit"]["network"]
            prefix = prefix64_from_48(transit_48, link["link_id"])

            if router_name == link["routeur_a"]:
                peer_ip = iface_addr(prefix, 2).split("/")[0]
            else:
                peer_ip = iface_addr(prefix, 1).split("/")[0]

            peer_asn = int(intent["AS"][as_v]["asnumber"])
            send(tn, f"neighbor {peer_ip} remote-as {peer_asn}")
            ebgp_peers.append(peer_ip)

    # iBGP: Route Reflectors (plus de full-mesh)
    ibgp_peers = []

    rr_names = RR_BY_AS.get(as_r, [])
    rr_loopbacks = []

    for rr in rr_names:
        idx_rr = intent["routeurs"][rr]["index"]
        rr_lo = loopback_from_as48(intent["AS"][as_r]["network"], idx_rr).split("/")[0]
        rr_loopbacks.append(rr_lo)

    # cas router est RR
    if router_name in rr_names:
        for rr, rr_lo in zip(rr_names, rr_loopbacks): # zip(..) pour parcourir 2 listes en même temps, élément par élément
            if rr == router_name:
                continue
            send(tn, f"neighbor {rr_lo} remote-as {asn}")
            send(tn, f"neighbor {rr_lo} update-source Loopback0")
            ibgp_peers.append(rr_lo)

        for r2, info2 in intent["routeurs"].items():
            if info2["as"] != as_r:
                continue
            if r2 in rr_names:
                continue

            idx2 = info2["index"]
            lo2 = loopback_from_as48(intent["AS"][as_r]["network"], idx2).split("/")[0]
            send(tn, f"neighbor {lo2} remote-as {asn}")
            send(tn, f"neighbor {lo2} update-source Loopback0")
            ibgp_peers.append(lo2)

    # cas router n'est pas RR
    else:
        for rr_lo in rr_loopbacks:
            send(tn, f"neighbor {rr_lo} remote-as {asn}")
            send(tn, f"neighbor {rr_lo} update-source Loopback0")
            ibgp_peers.append(rr_lo)
    

    # AF IPv6
    send(tn, "address-family ipv6")

    for p in ebgp_peers:
        send(tn, f"neighbor {p} activate")
    for p in ibgp_peers:
        send(tn, f"neighbor {p} activate")

        if router_name in rr_names:
            send(tn, f"neighbor {p} next-hop-self")

    send(tn, "exit")

    # RR config
    if router_name in rr_names:
        for r2, info2 in intent["routeurs"].items():
            if info2["as"] != as_r:
                continue
            if r2 in rr_names: # faut pas mettre un RR-client à soi-même ni aux autres RRs
                continue

            idx2 = info2["index"]
            lo2 = loopback_from_as48(intent["AS"][as_r]["network"], idx2).split("/")[0]
            send(tn, f"neighbor {lo2} route-reflector-client")         

    # policies (redistribute + aggregate) uniquement sur bordure
    igp = intent["AS"][as_r]["igp"]
    net48 = intent["AS"][as_r]["network"]

    if border and igp == "RIP":
        send(tn, f"redistribute rip {intent['AS'][as_r]['nom_process']}")
        send(tn, f"aggregate-address {net48} summary-only")

    if border and igp == "OSPF":
        send(tn, f"redistribute ospf {OSPF_PROCESS_ID}")
        send(tn, f"aggregate-address {net48} summary-only")

    send(tn, "end")
    send(tn, "write memory", delay=0.5)

    # Retour BGP -> RIP dans AS X (seulement bordure)
    if border and igp == "RIP":
        send(tn, "conf t")
        send(tn, f"ipv6 router rip {intent['AS'][as_r]['nom_process']}")
        send(tn, f"redistribute bgp {intent['AS'][as_r]['asnumber']} metric 1")
        send(tn, "end")
        send(tn, "write memory", delay=0.5)

    tn.close()


# ---------------------- Communautés ----------------------

def config_communities(node: Node, router_name: str, neigh):
    """
    Applique les communautés BGP et politiques de routage.
    Args:
        node (Node): Node GNS3.
        router_name (str): Nom du routeur.
        neigh (dict): Voisins du routeur.
    Returns:
        None
    """
    as_r = intent["routeurs"][router_name]["as"]
    asn = int(intent["AS"][as_r]["asnumber"])
    net48 = intent["AS"][as_r]["network"]
    border = is_border(router_name, intent, neigh)
    ebgp_neighbors = []  # [(peer_ip, relation)]

    tn = telnetlib.Telnet(node.console_host, node.console)
    time.sleep(1)
    send(tn, "")
    send(tn, "enable")
    send(tn, "conf t")

    # Nouvelle syntaxe communautés BGP
    send(tn, "ip bgp-community new-format")

    # Voisins iBGP
    ibgp_peers = []

    for r2, info2 in intent["routeurs"].items():
        if r2 == router_name:
            continue
        if info2["as"] != as_r:
            continue

        idx2 = info2["index"]
        lo2 = loopback_from_as48(net48, idx2).split("/")[0]  # IP seule
        ibgp_peers.append(lo2)
    
    # Communautés et local pref sur bordure
    if border:
        # 1) Commmunity-lists
        send(tn, "no ip community-list standard CLIENT")
        send(tn, "no ip community-list standard PEER")
        send(tn, "no ip community-list standard PROVIDER")
        send(tn, f"ip community-list standard CLIENT permit {asn}:100")
        send(tn, f"ip community-list standard PEER permit {asn}:200")
        send(tn, f"ip community-list standard PROVIDER permit {asn}:300")

        # 2) Route-maps IN
        send(tn, "route-map IN-CLIENT permit 10")
        send(tn, f"set community {asn}:100 additive")
        send(tn, "set local-preference 200")
        send(tn, "exit")

        send(tn, "route-map IN-PEER permit 10")
        send(tn, f"set community {asn}:200 additive")
        send(tn, "set local-preference 150")
        send(tn, "exit")

        send(tn, "route-map IN-PROVIDER permit 10")
        send(tn, f"set community {asn}:300 additive")
        send(tn, "set local-preference 100")
        send(tn, "exit")

        # 3) Route-maps OUT
        send(tn, "route-map OUT-CLIENT permit 10")
        send(tn, "exit")

        send(tn, "route-map OUT-PEER permit 10")
        send(tn, f"match community CLIENT")
        send(tn, "exit")
        send(tn, "route-map OUT-PEER deny 20")
        send(tn, "exit")

        send(tn, "route-map OUT-PROVIDER permit 10")
        send(tn, f"match community CLIENT")
        send(tn, "exit")
        send(tn, "route-map OUT-PROVIDER deny 20")
        send(tn, "exit")

        for v in neigh[router_name]:
            as_v = intent["routeurs"][v]["as"]
            if as_v == as_r:
                continue

            link=get_link(router_name, v, intent["links"])
            if not link or not link.get("transit", False):
                continue

            transit_48 = intent["transit"]["network"]
            prefix64 = prefix64_from_48(transit_48, link["link_id"])
            
            if router_name == link["routeur_a"]:
                peer_ip = iface_addr(prefix64, 2).split("/")[0]
            else:
                peer_ip = iface_addr(prefix64, 1).split("/")[0]

            relation = relation_between(as_r, as_v)

            ebgp_neighbors.append((peer_ip, relation))

        send(tn, f"router bgp {asn}")
        send(tn, "address-family ipv6")

        for peer_ip, relation in ebgp_neighbors:
            if relation == "CLIENT":
                in_rm = "IN-CLIENT"
                out_rm = "OUT-CLIENT"
            elif relation == "PROVIDER":
                in_rm = "IN-PROVIDER"
                out_rm = "OUT-PROVIDER"
            elif relation == "PEER":
                in_rm = "IN-PEER"
                out_rm = "OUT-PEER"
            else:
                continue

            send(tn, f"neighbor {peer_ip} route-map {in_rm} in") 
            send(tn, f"neighbor {peer_ip} route-map {out_rm} out")

        send(tn, "exit")
        send(tn, "exit")
    
    # On applique send-community aux iBGP
    send(tn, f"router bgp {asn}")
    send(tn, "address-family ipv6")
    for lo in ibgp_peers:
        send(tn, f"neighbor {lo} send-community")
   
    send(tn, "end")
    send(tn, "write memory", delay=0.5)
    tn.close()

# ---------------------- Main ----------------------

def main():
    neigh = build_neighbors(intent)

    for router_name, router_info in intent.get("routeurs", {}).items():
        node = Node(project_id=project.project_id, name=router_name, connector=server)
        node.get()

        tn = telnetlib.Telnet(node.console_host, node.console)
        send(tn, "no")
        send(tn, "")
        tn.close()

        ensure_node_started(node, wait_s=2)

        as_routeur = router_info["as"]
        protocole = intent["AS"][as_routeur]["igp"]

        if protocole == "RIP":
            config_RIP(node, router_name, as_routeur)
        elif protocole == "OSPF":
            config_OSPF(node, router_name, as_routeur)

        # BGP après IGP
        config_BGP(node, router_name, neigh)

        # Communautés après BGP
        config_communities(node, router_name, neigh)

    print("Configuration terminée.")

if __name__ == "__main__":
    main()