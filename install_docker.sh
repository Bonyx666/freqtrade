id=$(grep '^ID=' /etc/os-release | cut -d'=' -f2 | tr -d '"')
echo "Distro used is $id"
# sudo apt-get update
# sudo apt-get install -y ca-certificates curl gnupg
# sudo install -m 0755 -d /etc/apt/keyrings
# curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
# sudo chmod a+r /etc/apt/keyrings/docker.gpg

# echo \
#   "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
#   "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
#   sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
# sudo apt-get update

# sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# sudo curl -L "https://github.com/docker/compose/releases/download/v2.27.1/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
# sudo chmod +x /usr/local/bin/docker-compose

# sudo groupadd -f docker
# sudo usermod -aG docker $USER
# newgrp docker