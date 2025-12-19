import os
import json
import time
import telnetlib
from ipaddress import IPv6Network

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

def reset_router(node: Node):
    """Optionnel: wipe config + reload"""
    tn = telnetlib.Telnet(node.console_host, node.console)
    time.sleep(1)
    send(tn, "")
    send(tn, "enable")
    send(tn, "write erase")
    send(tn, "")
    send(tn, "reload")
    send(tn, "")
    send(tn, "no")  # ne pas sauvegarder
    tn.close()


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

def get_link_prefix(router_a: str, router_b: str, links):
    """
    Retourne (prefix, router_a_is_link_routeur_a)
    - prefix = link["sous_res"]
    - True si router_a correspond à link["routeur_a"], False sinon
    """
    for link in links:
        if link["routeur_a"] == router_a and link["routeur_b"] == router_b:
            return link["sous_res"], True
        if link["routeur_b"] == router_a and link["routeur_a"] == router_b:
            return link["sous_res"], False
    return None, None


# ---------------------- IGP configs ----------------------

def config_RIP(node: Node, router_name: str, as_routeur: str):
    tn = telnetlib.Telnet(node.console_host, node.console)
    time.sleep(1)
    send(tn, "")

    send(tn, "enable")
    send(tn, "configure terminal")
    send(tn, "ipv6 unicast-routing")

    nom_process = intent["AS"][as_routeur]["nom_process"]
    send(tn, f"ipv6 router rip {nom_process}")
    send(tn, "exit")

    # Loopback
    loopback_address = intent["routeurs"][router_name]["loopback"]
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
            ip = iface_addr(link["sous_res"], 1)
        elif router_name == link["routeur_b"]:
            voisin = link["routeur_a"]
            iface = link["interface_b"]
            ip = iface_addr(link["sous_res"], 2)
        else:
            continue

        send(tn, f"interface {iface}")
        send(tn, "ipv6 enable")
        send(tn, f"ipv6 address {ip}")
        if intent["routeurs"][voisin]["as"] == as_routeur:
            send(tn, f"ipv6 rip {nom_process} enable")
        send(tn, "no shutdown")
        send(tn, "exit")

    send(tn, "end")
    time.sleep(1)
    send(tn, "write memory", delay=0.5)
    tn.close()


def config_OSPF(node: Node, router_name: str, as_routeur: str,
                process_id: int = OSPF_PROCESS_ID, area: int = DEFAULT_OSPF_AREA):
    tn = telnetlib.Telnet(node.console_host, node.console)
    time.sleep(1)
    tn.write(b"\r\n")
    time.sleep(0.5)
    #Début des commandes :
    tn.write(b"enable\r\n")
    time.sleep(0.3)
    tn.write(b"configure terminal\r\n")
    time.sleep(0.3)
    tn.write(b"ipv6 unicast-routing\r\n")
    time.sleep(0.3)
    tn.write(b"ipv6 unicast-routing\r\n")
    time.sleep(0.3)
    #routeur ID :
    tn.write(b"ipv6 router ospf 1\r\n") #1 variable ?
    time.sleep(0.3)
    tn.write(b"router id {intent[routeurs][router_name].get('routeurID')}\r\n")
    time.sleep(0.3)
    tn.write(b"exit\r\n")
    time.sleep(0.3)
    #loopback :
    tn.write(b"interface Loopback0\r\n")
    time.sleep(0.3)
    tn.write(b"ipv6 enable\r\n")
    time.sleep(0.3)
    tn.write(b"ipv6 address {intent[routeurs][router_name].get('loopback')}\r\n")
    time.sleep(0.3)
    tn.write(b"ipv6 ospf 1 area 0\r\n") #voir si 1 et 0 peuvent être variables
    time.sleep(0.3)
    tn.write(b"exit\r\n")
    time.sleep(0.3)
    #liens avec voisins :
    for link in intent["links"]:
        if router_name == link["routeur_a"]:
            voisin = link["routeur_b"]
            tn.write(b"interface {link[interface_a]}\r\n")
            time.sleep(0.3)
            tn.write(b"ipv6 enable\r\n")
            time.sleep(0.3)
            tn.write(b"ipv6 address {link[sous_res]}\r\n")
            time.sleep(0.3)
            if intent["routeurs"][voisin].get("as") == as_routeur:
                tn.write(b"ipv6 ospf 1 area 0\r\n")
                time.sleep(0.3)
        elif router_name == link["routeur_b"]:
            voisin = link["routeur_a"]
            tn.write(b"interface {link[interface_b]}\r\n")
            time.sleep(0.3)
            tn.write(b"ipv6 enable\r\n")
            time.sleep(0.3)
            tn.write(b"ipv6 address {link[sous_res]}\r\n")
            time.sleep(0.3)
            if intent["routeurs"][voisin].get("as") == as_routeur:
                tn.write(b"ipv6 ospf 1 area 0\r\n")
                time.sleep(0.3)
        tn.write(b"no shutdown\r\n")
        time.sleep(0.3)
        tn.write(b"exit\r\n")
        time.sleep(0.3)
    tn.write(b"end\r\n")
    tn.write(b"write\r\n")
    tn.close()


# ---------------------- BGP config ----------------------

def config_BGP(node: Node, router_name: str, neigh, y_hub: str = "Y1"):
    as_r = intent["routeurs"][router_name]["as"]
    border = is_border(router_name, intent, neigh)

    # On configure BGP si :
    # - routeur bordure (inter-AS) OU
    # - routeur dans AS Y (iBGP interne)
    if (not border) and (as_r != "Y"):
        return

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

            prefix, router_is_a = get_link_prefix(router_name, v, intent["links"])
            if not prefix:
                continue

            if router_is_a:
                peer_ip = iface_addr(prefix, 2).split("/")[0]
            else:
                peer_ip = iface_addr(prefix, 1).split("/")[0]

            peer_asn = int(intent["AS"][as_v]["asnumber"])
            send(tn, f"neighbor {peer_ip} remote-as {peer_asn}")
            ebgp_peers.append(peer_ip)

    # iBGP: uniquement AS Y, hub-and-spoke avec Y1
    ibgp_peers = []
    if as_r == "Y":
        if router_name == y_hub:
            for r2, info2 in intent["routeurs"].items():
                if r2 == y_hub or info2["as"] != "Y":
                    continue
                lo = info2["loopback"].split("/")[0]
                send(tn, f"neighbor {lo} remote-as {asn}")
                send(tn, f"neighbor {lo} update-source Loopback0")
                ibgp_peers.append(lo)
        else:
            hub_lo = intent["routeurs"][y_hub]["loopback"].split("/")[0]
            send(tn, f"neighbor {hub_lo} remote-as {asn}")
            send(tn, f"neighbor {hub_lo} update-source Loopback0")
            ibgp_peers.append(hub_lo)

    # AF IPv6
    send(tn, "address-family ipv6")
    for p in ebgp_peers:
        send(tn, f"neighbor {p} activate")
    for p in ibgp_peers:
        send(tn, f"neighbor {p} activate")

    # next-hop-self sur le hub
    if as_r == "Y" and router_name == y_hub:
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
    if border and as_r == "X":
        send(tn, "conf t")
        send(tn, f"ipv6 router rip {intent['AS']['X']['nom_process']}")
        send(tn, f"redistribute bgp {intent['AS']['X']['asnumber']} metric 1")
        send(tn, "end")
        send(tn, "write memory", delay=0.5)

    tn.close()


# ---------------------- Main ----------------------

def main():
    neigh = build_neighbors(intent)

    for router_name, router_info in intent.get("routeurs", {}).items():
        node = Node(project_id=project.project_id, name=router_name, connector=server)
        node.get()

        # Optionnel : reset
        # reset_router(node)

        ensure_node_started(node, wait_s=2)

        as_routeur = router_info["as"]
        protocole = intent["AS"][as_routeur]["igp"]

        if protocole == "RIP":
            config_RIP(node, router_name, as_routeur)
        elif protocole == "OSPF":
            config_OSPF(node, router_name, as_routeur)

        # BGP après IGP
        config_BGP(node, router_name, neigh, y_hub="Y1")

    print("Configuration terminée.")

if __name__ == "__main__":
    main()
