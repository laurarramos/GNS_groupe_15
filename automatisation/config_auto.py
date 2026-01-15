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

with open("intent.json", "r", encoding="utf-8") as f:
    intent = json.load(f)

server = Gns3Connector(url=GNS3_URL)
project = Project(name="structure_vide", connector=server)
project.get()
project.open()
project.get_nodes()

# ---------------------- Utils Telnet & IP helpers ----------------------

def send(tn, cmd: str, delay: float = TELNET_DELAY):
    tn.write((cmd + "\r\n").encode("ascii", errors="ignore"))
    time.sleep(delay)

def iface_addr(prefix: str, host_id: int) -> str:
    """
    prefix = '2001:db8:100:0::/64' -> retourne '2001:db8:100:0::1/64' ou '...::2/64'
    """
    net = IPv6Network(prefix, strict=False)
    return f"{net.network_address + host_id}/{net.prefixlen}"

def ensure_node_started(node: Node, wait_s: float = 2.0):
    node.get()
    if node.status != "started":
        node.start()
        time.sleep(wait_s)
        node.get()

def prefix64_from_48(net48: str, link_id: int) -> str:
    n48 = IPv6Network(net48, strict=False)
    base = int(n48.network_address)

    # Le subnet-id (/64) correspond aux 16 bits entre /48 et /64.
    # On place link_id dans ces 16 bits => décalage de 64 bits.
    addr64 = base + (int(link_id) << 64)
    n64 = IPv6Network((addr64, 64))
    return f"{n64.network_address}/{n64.prefixlen}"

def loopback_from_as48(as48: str, idx: int) -> str:
    net48 = IPv6Network(as48, strict=False)
    base = int(net48.network_address)

    addr = base + (0xFFFF << 64) + int(idx)
    n128 = IPv6Network((addr, 128))
    return f"{n128.network_address}/{n128.prefixlen}"


# ---------------------- Topology helpers ----------------------

def build_neighbors(intent_dict):
    neigh = {r: [] for r in intent_dict["routeurs"].keys()}
    for link in intent_dict["links"]:
        a, b = link["routeur_a"], link["routeur_b"]
        neigh[a].append(b)
        neigh[b].append(a)
    return neigh

def is_border(router: str, intent_dict, neigh):
    as_r = intent_dict["routeurs"][router]["as"]
    return any(intent_dict["routeurs"][v]["as"] != as_r for v in neigh[router])

def get_link(router_a: str, router_b: str, links):
    for link in links:
        a, b = link["routeur_a"], link["routeur_b"]
        if (a == router_a and b == router_b) or (a == router_b and b == router_a):
            return link
    return None


# ---------------------- IGP configs ----------------------

def config_RIP(node: Node, router_name: str, as_routeur: str):
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

            if as_v in intent["AS"][as_r]["providers"]:
                pass
            elif as_v in intent["AS"][as_r]["customers"]:
                pass
            elif as_v in intent["AS"][as_r]["peers"]:
                pass

    # iBGP: full-mesh
    ibgp_peers = []
    for r2, info2 in intent["routeurs"].items():
        if r2 == router_name:
            continue
        if info2["as"] != as_r:
            continue
        idx2 = info2["index"]
        as48 = intent["AS"][as_r]["network"]  # même AS (iBGP)
        lo = loopback_from_as48(as48, idx2).split("/")[0]
        send(tn, f"neighbor {lo} remote-as {asn}")
        send(tn, f"neighbor {lo} update-source Loopback0")
        ibgp_peers.append(lo)

    # AF IPv6
    send(tn, "address-family ipv6")
    for p in ebgp_peers:
        send(tn, f"neighbor {p} activate")
    for p in ibgp_peers:
        send(tn, f"neighbor {p} activate")
    if border:
        for p in ibgp_peers:
            send(tn, f"neighbor {p} next-hop-self")       

    # policies (redistribute + aggregate) uniquement sur bordure
    igp = intent["AS"][as_r]["igp"]
    net48 = intent["AS"][as_r]["network"]

    if border and igp == "RIP":
        send(tn, f"redistribute rip {intent['AS'][as_r]['nom_process']}")
        send(tn, f"aggregate-address {net48} summary-only")

    if border and igp == "OSPF":
        send(tn, f"redistribute ospf {OSPF_PROCESS_ID}")
        send(tn, f"aggregate-address {net48} summary-only")

    send(tn, "exit-address-family")
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

    print("Configuration terminée.")

if __name__ == "__main__":
    main()