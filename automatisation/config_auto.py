import json
import re
import time
import telnetlib
import sys

from gns3fy import Gns3Connector, Project, Node

GNS3_URL = "http://127.0.0.1:3080"         

with open("intent.json", "r", encoding="utf-8") as f:
    intent = json.load(f)

server = Gns3Connector(url=GNS3_URL)
project = Project(name="structure_vide", connector=server)
project.get()      
project.open()     
project.get_nodes()

def reset_router(node):
    tn = telnetlib.Telnet(node.console_host, node.console)
    time.sleep(1)
    tn.write(b"\r\n")
    time.sleep(0.3)
    tn.write(b"enable\r\n")
    time.sleep(0.3)
    tn.write(b"write erase\r\n")
    time.sleep(0.3)
    tn.write(b"\r\n")
    time.sleep(0.5)
    tn.write(b"reload\r\n")
    time.sleep(0.3)
    tn.write(b"\r\n")
    time.sleep(0.5)

    tn.write(b"no\r\n")  # ne pas sauvegarder
    tn.close()

def config_RIP(node,router_name,as_routeur):
    #ouverture écriture dans console :
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
    nom_process = intent["AS"][as_routeur].get("nom_process")
    tn.write(f"ipv6 router rip {nom_process}\r\n".encode("ascii"))
    time.sleep(0.3)
    #loopback :
    tn.write(b"interface Loopback0\r\n")
    time.sleep(0.3)
    tn.write(b"ipv6 enable\r\n")
    time.sleep(0.3)
    loopback_address = intent["routeurs"][router_name].get("loopback")
    tn.write(f"ipv6 address {loopback_address}\r\n".encode("ascii"))
    time.sleep(0.3)
    tn.write(f"ipv6 rip {nom_process} enable\r\n".encode("ascii"))
    time.sleep(0.3)
    tn.write(b"exit\r\n")
    time.sleep(0.3)
    #liens avec voisins :
    for link in intent["links"]:
        if router_name == link["routeur_a"]:
            voisin = link["routeur_b"]
            tn.write(f"interface {link["interface_a"]}\r\n".encode("ascii"))
            time.sleep(0.3)
            tn.write(b"ipv6 enable\r\n")
            time.sleep(0.3)
            tn.write(f"ipv6 address {link["sous_res"]}\r\n".encode("ascii"))
            time.sleep(0.3)
            if intent["routeurs"][voisin].get("as") == as_routeur:
                tn.write(f"ipv6 rip {nom_process} enable\r\n".encode("ascii"))
                time.sleep(0.3)
            tn.write(b"no shutdown\r\n")
            time.sleep(0.3)
            tn.write(b"exit\r\n")
            time.sleep(0.3)
        elif router_name == link["routeur_b"]:
            voisin = link["routeur_a"]
            tn.write(f"interface {link["interface_b"]}\r\n".encode("ascii"))
            time.sleep(0.3)
            tn.write(b"ipv6 enable\r\n")
            time.sleep(0.3)
            tn.write(f"ipv6 address {link["sous_res"]}\r\n".encode("ascii"))
            time.sleep(0.3)
            if intent["routeurs"][voisin].get("as") == as_routeur:
                tn.write(f"ipv6 rip {nom_process} enable\r\n".encode("ascii"))
                time.sleep(0.3)
            tn.write(b"no shutdown\r\n")
            time.sleep(0.3)
            tn.write(b"exit\r\n")
            time.sleep(0.3)
    tn.write(b"end\r\n")
    time.sleep(1)
    tn.write(b"write memory\r\n")
    tn.close()

def config_OSPF(node,router_name,as_routeur):
    #ouverture écriture dans console :
    tn = telnetlib.Telnet(node.console_host, node.console)
    time.sleep(1)
    tn.write(b"\r\n")
    time.sleep(0.5)
    #Début des commandes :
    tn.write(f"enable\r\n".encode("ascii"))
    time.sleep(0.3)
    tn.write(f"configure terminal\r\n".encode("ascii"))
    time.sleep(0.3)
    tn.write(f"ipv6 unicast-routing\r\n".encode("ascii"))
    time.sleep(0.3)
    #routeur ID :
    tn.write(f"ipv6 router ospf 1\r\n".encode("ascii")) #1 variable ?
    time.sleep(0.3)
    routeurID = intent["routeurs"][router_name].get("routeurID")
    tn.write(f"router-id {routeurID}\r\n".encode("ascii"))
    time.sleep(0.3)
    tn.write(b"exit\r\n")
    time.sleep(0.3)
    #loopback :
    tn.write(b"interface Loopback0\r\n")
    time.sleep(0.3)
    tn.write(b"ipv6 enable\r\n")
    time.sleep(0.3)
    loopback_address = intent["routeurs"][router_name].get("loopback")
    tn.write(f"ipv6 address {loopback_address}\r\n".encode("ascii"))
    time.sleep(0.3)
    tn.write(b"ipv6 ospf 1 area 0\r\n") #voir si 1 et 0 peuvent être variables
    time.sleep(0.3)
    tn.write(b"exit\r\n")
    time.sleep(0.3)
    #liens avec voisins :
    for link in intent["links"]:
        if router_name == link["routeur_a"]:
            voisin = link["routeur_b"]
            tn.write(f"interface {link["interface_a"]}\r\n".encode("ascii"))
            time.sleep(0.3)
            tn.write(b"ipv6 enable\r\n")
            time.sleep(0.3)
            tn.write(f"ipv6 address {link["sous_res"]}\r\n".encode("ascii"))
            time.sleep(0.3)
            if intent["routeurs"][voisin].get("as") == as_routeur:
                tn.write(b"ipv6 ospf 1 area 0\r\n")
                time.sleep(0.3)
            tn.write(b"no shutdown\r\n")
            time.sleep(0.3)
            tn.write(b"exit\r\n")
            time.sleep(0.3)
        elif router_name == link["routeur_b"]:
            voisin = link["routeur_a"]
            tn.write(f"interface {link["interface_b"]}\r\n".encode("ascii"))
            time.sleep(0.3)
            tn.write(b"ipv6 enable\r\n")
            time.sleep(0.3)
            tn.write(f"ipv6 address {link["sous_res"]}\r\n".encode("ascii"))
            time.sleep(0.3)
            if intent["routeurs"][voisin].get("as") == as_routeur:
                tn.write(b"ipv6 ospf 1 area 0\r\n")
                time.sleep(0.3)
            tn.write(b"no shutdown\r\n")
            time.sleep(0.3)
            tn.write(b"exit\r\n")
            time.sleep(0.3)
    tn.write(b"end\r\n")
    time.sleep(1)
    tn.write(b"write memory\r\n")
    tn.close()

def main():
    for router_name, router_info in intent.get("routeurs", {}).items():
        node = Node(project_id=project.project_id, name=router_name, connector=server)
        node.get()
        #renitialisation du routeur
        #reset_router(node)

        if node.status != "started":
            node.start()
            time.sleep(2)  
            node.get()
        #info générales du routeur
        as_routeur = intent["routeurs"][router_name].get("as")
        protocole_routeur = intent["AS"][as_routeur].get("igp")

        #configuration selon le protocole
        if protocole_routeur == "RIP":
            config_RIP(node, router_name, as_routeur)
        elif protocole_routeur == "OSPF":
            config_OSPF(node, router_name, as_routeur)


if __name__ == "__main__":
    main()