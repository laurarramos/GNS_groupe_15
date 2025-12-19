import json
import re
import time
import telnetlib
from ipaddress import IPv6Network
import sys

from gns3fy import Gns3Connector, Project, Node

GNS3_URL = "http://127.0.0.1:3080"         
DEFAULT_OSPF_AREA = 0
OSPF_PROCESS_ID = 1
TELNET_DELAY = 0.3

with open("intent.json", "r", encoding="utf-8") as f:
    intent = json.load(f)

server = Gns3Connector(url=GNS3_URL)
project = Project(name="structure_vide", connector=server)
project.get()      
project.open()     
project.get_nodes()

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
    tn.write(b"ipv6 router rip {intent[AS][as_routeur].get('nom_process')}\r\n")
    time.sleep(0.3)
    #loopback :
    tn.write(b"interface Loopback0\r\n")
    time.sleep(0.3)
    tn.write(b"ipv6 enable\r\n")
    time.sleep(0.3)
    tn.write(b"ipv6 address {intent[routeurs][router_name].get('loopback')}\r\n")
    time.sleep(0.3)
    tn.write(b"ipv6 rip {intent[AS][as_routeur].get('nom_process')} enable\r\n")
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
                tn.write(b"ipv6 rip {intent[AS][as_routeur].get('nom_process')} enable\r\n")
                time.sleep(0.3)
            tn.write(b"no shutdown\r\n")
            time.sleep(0.3)
            tn.write(b"exit\r\n")
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
                tn.write(b"ipv6 rip {intent[AS][as_routeur].get('nom_process')} enable\r\n")
                time.sleep(0.3)
            tn.write(b"no shutdown\r\n")
            time.sleep(0.3)
            tn.write(b"exit\r\n")
            time.sleep(0.3)
    tn.write(b"end\r\n")
    tn.write(b"write\r\n")
    tn.close()

def config_OSPF(node,router_name,as_routeur):
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

    #...
    tn.write(b"end\r\n")
    tn.write(b"write\r\n")
    tn.close()

def main():
    for router_name, router_info in intent.get("routeurs", {}).items():
        node = Node(project_id=project.project_id, name=router_name, connector=server)
        node.get()
        #info générales du routeur
        as_routeur = intent["routeurs"][router_name].get("as")
        protocole_routeur = intent["AS"][as_routeur].get("igp")

        #configuration selon le protocole
        if protocole_routeur == "RIP":
            config_RIP(node, router_name, as_routeur)
        elif protocole_routeur == "OSPF":
            config_OSPF(node, router_name, as_routeur)

    