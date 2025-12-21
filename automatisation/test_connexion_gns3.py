from gns3fy import Gns3Connector, Project

server = Gns3Connector(url="http://127.0.0.1:3080")
project = Project(name="structure_vide", connector=server)
project.get()

print("Projet trouvé :", project.project_id)
