#!/bin/bash
# Unofficial PlexDevelopment Products Installer
# Version: 2.1 (Root execution)
# This script automatically detects your Linux distribution and installs selected Plex products

#----- Color Definitions -----#
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

#----- Global Variables -----#
INSTALL_DIR="/var/www/plex"
NGINX_AVAILABLE="/etc/nginx/sites-available"
NGINX_ENABLED="/etc/nginx/sites-enabled"
# PLEX_USER="plexapps" # User to run services - REMOVED, running as root
# PLEX_GROUP="plexapps" # Group for the user - REMOVED
DISTRIBUTION=""
PKG_MANAGER=""
NODE_EXECUTABLE="/usr/bin/node" # Default path, verified later

#----- Utility Functions -----#
print_header() {
    # Headers can go to stdout or stderr, stderr is safer for capture
    echo -e "\n${BOLD}${PURPLE}#----- $1 -----#${NC}\n" >&2
}

print_step() {
    echo -e "${BLUE}[+] ${CYAN}$1${NC}" >&2
}

print_success() {
    echo -e "${GREEN}[✓] $1${NC}" >&2
}

print_error() {
    echo -e "${RED}[✗] $1${NC}" >&2
}

print_warning() {
    echo -e "${YELLOW}[!] $1${NC}" >&2
}

# Function to check if a command was successful
check_command() {
    local exit_status=$?
    local command_description=$1
    if [ $exit_status -ne 0 ]; then
        # Use direct echo to stderr for debugging, bypassing print_error
        echo -e "\033[0;31m[DEBUG CHECK_COMMAND FAILED] '$command_description' (Exit Status: $exit_status). Returning 1.\033[0m" >&2
        return 1
    fi
    return 0
}

# Function to check if a command exists (keep exit 1 here, as missing commands are fatal)
check_command_exists() {
    local cmd_name=$1
    if ! command -v "$cmd_name" &> /dev/null; then
        print_error "Required command '$cmd_name' not found. Please ensure dependencies are installed correctly. Aborting."
        # Error message already goes to stderr via print_error
        exit 1 # Exit is appropriate here
    fi
    return 0
}

#----- System Setup -----#

detect_system() {
    print_header "System Detection"
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRIBUTION=$ID
        print_step "Detected distribution: ${BOLD}$DISTRIBUTION${NC}"

        # Determine package manager
        if [ -x "$(command -v apt)" ]; then
            PKG_MANAGER="apt"
        elif [ -x "$(command -v dnf)" ]; then
            PKG_MANAGER="dnf"
        elif [ -x "$(command -v yum)" ]; then
            PKG_MANAGER="yum" # Treat yum like dnf for dependency installation
        elif [ -x "$(command -v pacman)" ]; then
            PKG_MANAGER="pacman"
        elif [ -x "$(command -v zypper)" ]; then
            PKG_MANAGER="zypper"
        else
            print_error "Unable to determine a supported package manager (apt, dnf, yum, pacman, zypper)."
            print_warning "Attempting to proceed, but dependency installation may fail."
            PKG_MANAGER="unknown"
        fi
        if [ "$PKG_MANAGER" != "unknown" ]; then
            print_success "Using package manager: ${BOLD}$PKG_MANAGER${NC}"
        fi
    else
        print_error "Unable to detect Linux distribution (/etc/os-release not found)."
        exit 1
    fi
}

install_dependencies() {
    print_header "Installing Dependencies"
    if [ "$PKG_MANAGER" == "unknown" ]; then
        print_warning "Skipping automatic dependency installation due to unknown package manager."
        print_warning "Please ensure the following are installed: curl, wget, git, unzip, nginx, certbot, python3-certbot-nginx, nodejs (20+), npm, tar, coreutils, dnsutils/bind-utils, net-tools, nano, zip, sudo"
        read -p "Press Enter to continue attempt..." </dev/tty
        return
    fi

    print_step "Updating package lists..."
    case $PKG_MANAGER in
        apt)
            sudo apt update -y || print_warning "apt update failed, proceeding anyway..."
            print_step "Installing packages for Debian/Ubuntu..."
            sudo apt install -y curl wget git unzip nginx certbot python3-certbot-nginx \
                dnsutils net-tools nano bind9-utils whois iputils-ping zip tar \
                software-properties-common apt-transport-https ca-certificates gnupg sudo coreutils
            check_command "apt install"
            # Install Node.js 20+
            print_step "Installing Node.js 20+..."
            curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
            check_command "Nodesource setup script"
            sudo apt install -y nodejs
            check_command "Node.js installation"
            ;;
        dnf|yum)
            sudo $PKG_MANAGER update -y || print_warning "$PKG_MANAGER update failed, proceeding anyway..."
            print_step "Installing packages for Fedora/CentOS/RHEL..."
            sudo $PKG_MANAGER install -y curl wget git unzip nginx certbot python3-certbot-nginx \
                bind-utils net-tools nano whois iputils zip tar \
                dnf-plugins-core sudo coreutils # yum-utils for CentOS 7
            check_command "$PKG_MANAGER install"
            # Install Node.js 20+
            print_step "Installing Node.js 20+..."
            curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo -E bash -
            check_command "Nodesource setup script"
            sudo $PKG_MANAGER install -y nodejs
            check_command "Node.js installation"
            ;;
        pacman)
            sudo pacman -Syu --noconfirm || print_warning "pacman update failed, proceeding anyway..."
            print_step "Installing packages for Arch Linux..."
            sudo pacman -S --noconfirm --needed curl wget git unzip nginx certbot certbot-nginx \
                bind dnsutils net-tools nano whois iputils inetutils zip tar sudo coreutils
            check_command "pacman install"
            # Install Node.js 20+
            print_step "Installing Node.js 20+..."
            sudo pacman -S --noconfirm --needed nodejs npm
            check_command "Node.js installation"
            ;;
        zypper)
            sudo zypper refresh || print_warning "zypper refresh failed, proceeding anyway..."
            print_step "Installing packages for openSUSE..."
            sudo zypper install -y curl wget git unzip nginx certbot python3-certbot-nginx \
                bind-utils net-tools nano whois iputils zip tar \
                sudo coreutils
            check_command "zypper install"
            # Install Node.js 20+
            print_step "Installing Node.js 20+..."
            sudo zypper install -y nodejs20
            check_command "Node.js installation"
            ;;
        *)
            print_error "Unsupported package manager: $PKG_MANAGER"
            exit 1
            ;;
    esac

    # Verify essential commands exist after installation attempt
    for cmd in curl wget git unzip nginx certbot node npm tar sudo systemctl useradd groupadd chown chmod ln rm mkdir tee find grep awk sed head tail date df free openssl ip; do
        check_command_exists "$cmd"
    done

    # Verify node version
    NODE_EXECUTABLE=$(command -v node) || NODE_EXECUTABLE="/usr/bin/node" # Fallback if command -v fails but installed
    if [ ! -x "$NODE_EXECUTABLE" ]; then
        print_error "Node.js executable not found or not executable at $NODE_EXECUTABLE. Installation cannot proceed."
        exit 1
    fi
    NODE_VERSION=$($NODE_EXECUTABLE -v)
    print_step "Node.js version: $NODE_VERSION (using $NODE_EXECUTABLE)"
    if [[ ! $NODE_VERSION =~ ^v(2[0-9]|[3-9][0-9]) ]]; then # Check for v20+
        print_warning "Node.js version 20+ is recommended. Your version ($NODE_VERSION) may be incompatible."
        read -p "Continue anyway? (y/n): " continue_install </dev/tty
        if [[ $continue_install != "y" && $continue_install != "Y" ]]; then
            print_error "Installation aborted."
            exit 1
        fi
    fi

    # Check for DNS lookup tools
    if ! command -v dig &> /dev/null && ! command -v nslookup &> /dev/null && ! command -v host &> /dev/null; then
        print_warning "No DNS lookup tools (dig, nslookup, or host) found. Domain validation may be limited."
    else
        print_success "DNS lookup tools found."
    fi

    print_success "Dependencies check complete."
}

# setup_plex_user() { ... } # REMOVED

#----- Firewall -----#
open_port() {
    local port=$1
    local description=$2

    print_step "Attempting to open port $port/tcp for $description..."

    # Check which firewall is in use
    if command -v ufw &> /dev/null; then
        if sudo ufw status | grep -qw "$port/tcp"; then
            print_success "Port $port already allowed in UFW."
        else
            sudo ufw allow "$port/tcp" comment "$description"
            if [ $? -eq 0 ]; then
                print_success "Port $port opened using UFW."
            else
                print_warning "Failed to open port with UFW. You may need to open it manually."
            fi
        fi
    elif command -v firewall-cmd &> /dev/null; then
        if sudo firewall-cmd --query-port=$port/tcp --permanent &>/dev/null; then
             print_success "Port $port already allowed in firewalld."
        else
            print_step "Opening port $port in firewalld..."
            sudo firewall-cmd --permanent --add-port=$port/tcp > /dev/null
            if [ $? -eq 0 ]; then
                print_step "Reloading firewalld..."
                sudo firewall-cmd --reload
                if [ $? -eq 0 ]; then
                    print_success "Port $port opened using firewalld."
                else
                    print_warning "Failed to reload firewalld. Rule might not be active yet."
                fi
            else
                print_warning "Failed to add port with firewall-cmd. You may need to open it manually."
            fi
        fi
    elif command -v iptables &> /dev/null; then
        # iptables check is complex, just attempt to add
        print_warning "Using iptables. Rule persistence depends on distribution setup (e.g., iptables-persistent, firewalld service)."
        if sudo iptables -C INPUT -p tcp --dport $port -j ACCEPT &>/dev/null; then
             print_success "iptables rule for port $port seems to exist."
        else
            sudo iptables -A INPUT -p tcp --dport $port -j ACCEPT
            if [ $? -eq 0 ]; then
                print_success "Port $port rule added using iptables (check persistence)."
            else
                print_warning "Failed to add iptables rule. You may need to open it manually."
            fi
        fi
    else
        print_warning "No supported firewall (UFW, firewalld) detected. Please open port $port manually."
    fi
}

#----- Domain/DNS Check -----#
check_domain_dns() {
    local domain=$1
    local skip_check=${2:-false}

    if [[ "$skip_check" == true ]]; then
        print_warning "Skipping DNS check for $domain as requested."
        return 0
    fi

    print_step "Checking DNS for domain: $domain"

    # Get server's public IP
    local server_ip
    server_ip=$(curl -s -m 5 https://ifconfig.me) || server_ip=$(curl -s -m 5 https://api.ipify.org) || server_ip=$(ip -4 addr show scope global | grep inet | awk '{print $2}' | cut -d / -f 1 | head -n 1)

    if [ -z "$server_ip" ]; then
        print_error "Could not determine server's public IP address."
        read -p "Enter server's public IP manually or press Enter to skip DNS check: " server_ip </dev/tty
        if [ -z "$server_ip" ]; then
             print_warning "Skipping DNS check due to missing server IP."
             return 0 # Allow skipping
        fi
    fi
    print_step "Server Public IP: $server_ip"

    local domain_ip=""
    local dns_tool=""

    if command -v dig &> /dev/null; then
        dns_tool="dig"
    elif command -v nslookup &> /dev/null; then
        dns_tool="nslookup"
    elif command -v host &> /dev/null; then
        dns_tool="host"
    else
        print_warning "No DNS lookup tools found. Cannot verify DNS automatically."
        read -p "Is the domain $domain correctly pointed (A record) to $server_ip? (y/n/skip): " dns_confirm </dev/tty
        if [[ $dns_confirm == "y" || $dns_confirm == "Y" || $dns_confirm == "skip" ]]; then
            if [[ $dns_confirm == "skip" ]]; then
                 print_warning "Skipping domain validation. SSL setup might fail."
            fi
            return 0
        else
            print_error "Manual confirmation failed. Please configure DNS."
            return 1
        fi
    fi

    print_step "Querying DNS for $domain using $dns_tool..."
    for i in 1 2 3; do # Retry DNS lookup
        case $dns_tool in
            dig) domain_ip=$(dig +short A "$domain" @8.8.8.8 | head -n1) ;; # Use Google DNS to bypass local cache issues
            nslookup) domain_ip=$(nslookup "$domain" 8.8.8.8 | grep -A1 'Name:' | grep 'Address:' | awk '{print $2}' | head -n1) ;;
            host) domain_ip=$(host "$domain" 8.8.8.8 | grep 'has address' | awk '{print $4}' | head -n1) ;;
        esac

        if [ -n "$domain_ip" ]; then
            print_step "Resolved IP: $domain_ip"
            if [ "$domain_ip" == "$server_ip" ]; then
                print_success "Domain $domain correctly points to this server ($server_ip)."
                return 0
            else
                print_warning "Domain $domain points to $domain_ip, but server IP is $server_ip."
                read -p "DNS mismatch. Check again? (y/n/skip): " dns_check </dev/tty
                if [[ $dns_check == "y" || $dns_check == "Y" ]]; then
                    print_step "Waiting 10 seconds before retry..."
                    sleep 10
                    continue
                elif [[ $dns_check == "skip" ]]; then
                    print_warning "Skipping domain validation despite mismatch. SSL setup might fail."
                    return 0
                else
                    print_error "Cannot proceed without correct DNS configuration."
                    return 1
                fi
            fi
        else
            print_warning "Domain $domain did not resolve to an IP address (attempt $i/3)."
            if [ $i -lt 3 ]; then
                 read -p "Check DNS again in 15 seconds? (y/n/skip): " dns_check </dev/tty
                 if [[ $dns_check == "y" || $dns_check == "Y" ]]; then
                     print_step "Waiting 15 seconds before retry..."
                     sleep 15
                     continue
                 elif [[ $dns_check == "skip" ]]; then
                     print_warning "Skipping domain validation. SSL setup might fail."
                     return 0
                 else
                     print_error "Cannot proceed without DNS resolution."
                     return 1
                 fi
            else
                 print_error "Domain $domain failed to resolve after multiple attempts."
                 read -p "Proceed anyway (SSL will likely fail)? (y/n): " proceed_anyway </dev/tty
                 if [[ $proceed_anyway == "y" || $proceed_anyway == "Y" ]]; then
                     print_warning "Proceeding without DNS resolution."
                     return 0 # Allow proceeding but it will likely fail later
                 else
                     return 1
                 fi
            fi
        fi
    done
    # Should not be reached if logic is correct, but as a fallback
    print_error "DNS check failed after retries."
    return 1
}


#----- Nginx & SSL -----#
setup_nginx() {
    local domain=$1
    local port=$2
    local product=$3
    local install_path=$4 # Needed for PlexStore 502 page root

    local nginx_conf_file="$NGINX_AVAILABLE/$domain.conf"

    print_step "Configuring Nginx for $product at $domain (proxying to localhost:$port)"

    if [ -f "$nginx_conf_file" ]; then
        print_warning "Nginx config file $nginx_conf_file already exists."
        read -p "Overwrite existing Nginx config? (y/n): " overwrite_nginx </dev/tty
        if [[ $overwrite_nginx != "y" && $overwrite_nginx != "Y" ]]; then
            print_step "Skipping Nginx configuration."
            # Ensure site is enabled if skipped
            if [ ! -L "$NGINX_ENABLED/$domain.conf" ]; then
                 sudo ln -sf "$nginx_conf_file" "$NGINX_ENABLED/" || print_warning "Failed to enable existing Nginx site."
            fi
            sudo nginx -t && sudo systemctl reload nginx || print_error "Nginx reload failed."
            return 0
        fi
        print_step "Overwriting existing Nginx config..."
    fi

    # Create Nginx config content - UPDATED to initially create HTTP-only config
    local nginx_config_content
    if [[ "$product" == "plexstore" ]]; then
        # Special config for PlexStore with 502 page - HTTPS disabled initially
        nginx_config_content=$(cat <<EOF
server {
    listen 80;
    server_name $domain;

    # We'll configure HTTPS redirect after obtaining certificate
    
    location / {
        proxy_pass http://localhost:$port;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s; # Increase timeout if needed
        proxy_connect_timeout 120s;
    }

    # Custom 502 error page
    error_page 502 /502.html;
    location = /502.html {
        root $install_path; # Use the actual install path
        internal; # Only serve internally
    }
}
EOF
)
    else
        # Standard config for other products - HTTPS disabled initially
        nginx_config_content=$(cat <<EOF
server {
    listen 80;
    server_name $domain;

    # We'll configure HTTPS redirect after obtaining certificate
    
    location / {
        proxy_pass http://localhost:$port;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s; # Increase timeout if needed
        proxy_connect_timeout 120s;
    }
}
EOF
)
    fi

    # Write the Nginx config file
    echo "$nginx_config_content" | sudo tee "$nginx_conf_file" > /dev/null
    check_command "Writing Nginx config $nginx_conf_file"

    # Enable site
    print_step "Enabling Nginx site for $domain..."
    sudo ln -sf "$nginx_conf_file" "$NGINX_ENABLED/"
    check_command "Enabling Nginx site"

    # Test Nginx config
    print_step "Testing Nginx configuration..."
    if sudo nginx -t; then
        print_success "Nginx configuration test successful."
        # Reload Nginx (instead of restart, less disruptive)
        print_step "Reloading Nginx service..."
        sudo systemctl reload nginx
        check_command "Nginx reload"
        print_success "Nginx configured and reloaded for $domain."
    else
        print_error "Nginx configuration test failed. Please check the Nginx config file: $nginx_conf_file"
        print_error "Run 'sudo nginx -t' manually for details."
        # Attempt to disable the broken site to prevent Nginx from failing completely
        sudo rm -f "$NGINX_ENABLED/$(basename "$nginx_conf_file")"
        print_warning "Disabled potentially broken Nginx site $domain.conf to allow Nginx to run."
        exit 1 # Abort installation if Nginx config is bad
    fi
}

setup_ssl() {
    local domain=$1
    local email=$2

    print_step "Setting up SSL for $domain using Certbot..."

    # Check if certificate already exists
    if sudo certbot certificates | grep -q "Domains: $domain"; then
        print_warning "SSL certificate for $domain already exists."
        read -p "Attempt to renew/reinstall? (y/n): " renew_ssl </dev/tty
        if [[ $renew_ssl != "y" && $renew_ssl != "Y" ]]; then
            print_step "Skipping SSL setup."
            # Ensure Nginx is reloaded to pick up existing SSL config if needed
            sudo systemctl reload nginx || print_warning "Nginx reload failed after skipping SSL setup."
            return 0
        fi
        print_step "Attempting to renew/reinstall SSL certificate..."
    fi
    
    # Now use --nginx flag to auto-configure Nginx for SSL
    # This will modify the Nginx config to add SSL and redirection
    sudo certbot --nginx -d "$domain" --non-interactive --agree-tos --email "$email" --redirect --keep-until-expiring

    if [ $? -eq 0 ]; then
        print_success "SSL certificate obtained/updated and Nginx configured successfully for $domain."
        print_step "Verifying Nginx configuration after SSL setup..."
        if sudo nginx -t; then
            print_step "Reloading Nginx to apply SSL changes..."
            sudo systemctl reload nginx
            check_command "Nginx reload after SSL setup"
        else
            print_error "Nginx configuration test failed after SSL setup!"
            print_warning "Certbot may have created an invalid Nginx configuration."
            print_warning "You may need to manually fix the Nginx config at $NGINX_AVAILABLE/$domain.conf"
        fi
    else
        print_error "Certbot failed to obtain/update SSL certificate for $domain."
        print_warning "Check Certbot logs (/var/log/letsencrypt/letsencrypt.log) for details."
        print_warning "The application will work over HTTP if Nginx is running, but HTTPS will fail."
        print_warning "Try running: sudo certbot --nginx -d \"$domain\" manually to debug."
        # Don't exit here, allow installation to finish but warn user
    fi
}

#----- Service Management (Systemd) -----#
create_systemd_service() {
    local product=$1
    local install_path=$2
    local service_name="plex-$product"
    local service_file="/etc/systemd/system/$service_name.service"

    print_step "Creating systemd service file for $product..."

    if [ -f "$service_file" ]; then
        print_warning "Systemd service file $service_file already exists."
        read -p "Overwrite existing service file? (y/n): " overwrite_service </dev/tty
        if [[ $overwrite_service != "y" && $overwrite_service != "Y" ]]; then
            print_step "Skipping systemd service creation."
            # Ensure service is enabled and started if skipped
            if ! sudo systemctl is-enabled "$service_name" &>/dev/null; then
                 sudo systemctl enable "$service_name" || print_warning "Failed to enable existing service $service_name."
            fi
            sudo systemctl start "$service_name" || print_warning "Failed to start existing service $service_name. Check logs: journalctl -u $service_name"
            return 0
        fi
        print_step "Overwriting existing systemd service file..."
        sudo systemctl stop "$service_name" # Stop before overwriting
    fi

    # Create the systemd service file content
    local service_content
    service_content=$(cat <<EOF
[Unit]
Description=PlexDevelopment - $product Service
After=network.target nginx.service 

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=$install_path
ExecStart=$NODE_EXECUTABLE .
Restart=on-failure
RestartSec=10 
TimeoutStartSec=30s
StandardOutput=syslog 
StandardError=syslog
SyslogIdentifier=$service_name

[Install]
WantedBy=multi-user.target
EOF
)

    # Write the service file
    echo "$service_content" | sudo tee "$service_file" > /dev/null
    check_command "Writing systemd service file $service_file"
    sudo chmod 644 "$service_file" # Set standard permissions

    # Reload systemd, enable and start the service
    print_step "Reloading systemd daemon..."
    sudo systemctl daemon-reload
    check_command "systemctl daemon-reload"

    print_step "Enabling service $service_name to start on boot..."
    sudo systemctl enable "$service_name"
    check_command "systemctl enable $service_name"

    print_step "Starting service $service_name..."
    if sudo systemctl start "$service_name"; then
        print_success "Service $service_name started successfully."
        # Optional: Check status briefly
        sleep 2 # Give service a moment to start/fail
        if ! sudo systemctl is-active --quiet "$service_name"; then
             print_warning "Service $service_name started but seems inactive. Check logs."
             print_warning "Run: sudo journalctl -u $service_name -n 50 --no-pager"
        fi
    else
        print_error "Service $service_name failed to start."
        print_error "Check the service logs for errors:"
        print_error "sudo journalctl -u $service_name -n 50 --no-pager"
        print_error "Also check the application's config file in $install_path"
        # Don't exit, let user troubleshoot
    fi
}

#----- Installation Logic -----#

check_existing_installation() {
    local product="$1"
    local install_path="$INSTALL_DIR/$product"
    if [ -d "$install_path" ]; then
        print_warning "An existing installation of $product was found at $install_path"
        read -p "Do you want to REMOVE the existing installation and proceed? (y/n): " purge_choice </dev/tty
        if [[ "$purge_choice" == "y" || "$purge_choice" == "Y" ]]; then
            print_step "Stopping service if running..."
            sudo systemctl stop "plex-$product" &>/dev/null # Ignore errors if not running
            print_step "Removing existing installation directory $install_path..."
            sudo rm -rf "$install_path"
            check_command "Removing existing installation directory"
            print_success "Existing installation removed."
            return 0 # Indicate removal happened
        else
            print_warning "Installation aborted to preserve existing files."
            exit 0
        fi
    fi
    return 1 # Indicate no removal happened
}

find_archive_files() {
    local product="$1"
    local search_dirs=("/home" "/root" "/tmp" "/var/tmp" ".") # Added current dir
    local max_depth=3
    local found_archives=()
    local found_unobf_archives=()
    local log_file="./archive_search_log.txt" # Log in current dir

    echo "Archive search started: $(date)" > "$log_file"
    echo "Searching for product: $product" >> "$log_file"
    echo "Searching in: ${search_dirs[*]}" >> "$log_file"

    print_step "Searching for archive files for '$product' (check $log_file for details)..."

    # Search using find -iregex for better matching (case-insensitive)
    local product_pattern_unobf=".*${product}.*unobf.*\.\(zip\|rar\)"
    local product_pattern=".*${product}.*\.\(zip\|rar\)"
    local generic_pattern=".*\.\(zip\|rar\)"

    # Find unobfuscated versions first
    for dir in "${search_dirs[@]}"; do
        if [ -d "$dir" ]; then
            while IFS= read -r file; do
                # Basic check to avoid adding duplicates if search paths overlap
                if [[ ! " ${found_unobf_archives[@]} " =~ " ${file} " ]]; then
                    found_unobf_archives+=("$file")
                    echo "Found unobfuscated match: $file" >> "$log_file"
                fi
            done < <(find "$dir" -maxdepth "$max_depth" -type f -iregex "$product_pattern_unobf" 2>/dev/null)
        fi
    done

    # Find regular versions, excluding unobf already found
    for dir in "${search_dirs[@]}"; do
        if [ -d "$dir" ]; then
            while IFS= read -r file; do
                 # Check it's not already in unobf list and not already in regular list
                 if [[ ! " ${found_unobf_archives[@]} " =~ " ${file} " ]] && \
                    [[ ! " ${found_archives[@]} " =~ " ${file} " ]] && \
                    [[ ! "$file" =~ -Unobf ]]; then # Double check name just in case
                    found_archives+=("$file")
                    echo "Found product match: $file" >> "$log_file"
                 fi
            done < <(find "$dir" -maxdepth "$max_depth" -type f -iregex "$product_pattern" 2>/dev/null)
        fi
    done

    # Combine arrays: unobf first, then regular
    local all_found_archives=("${found_unobf_archives[@]}" "${found_archives[@]}")

    # If no product-specific found, search for generic archives
    if [ ${#all_found_archives[@]} -eq 0 ]; then
        print_warning "No product-specific archives found. Searching for any recent archives..."
        for dir in "${search_dirs[@]}"; do
            if [ -d "$dir" ]; then
                # Find recent archives, limit to 10
                while IFS= read -r file; do
                    if [[ ! " ${all_found_archives[@]} " =~ " ${file} " ]]; then
                        all_found_archives+=("$file")
                        echo "Found generic archive: $file" >> "$log_file"
                    fi
                done < <(find "$dir" -maxdepth "$max_depth" -type f -iregex "$generic_pattern" -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 10 | cut -d' ' -f2-)
            fi
        done
    fi

    if [ ${#all_found_archives[@]} -gt 0 ]; then
        echo "----------------------------------------"
        echo "FOUND ${#all_found_archives[@]} ARCHIVE FILES:"
        echo "----------------------------------------"
        local i=1
        # Use a temporary array to display choices, as the original might be reordered
        local display_archives=("${all_found_archives[@]}")
        for archive in "${display_archives[@]}"; do
            local file_size
            file_size=$(du -h "$archive" 2>/dev/null | cut -f1 || echo "N/A")
            local display_name="$archive"
            # Mark unobfuscated versions clearly
            if [[ "$archive" == *"-Unobf"* || "$archive" == *"-unobf"* ]]; then
                display_name="${archive} ${YELLOW}[Source Code]${NC}"
            fi
            echo -e "$i) $display_name ($file_size)"
            i=$((i+1))
        done
        echo "0) Enter custom path"
        echo "----------------------------------------"
        while true; do
            read -p "Select archive file option (0-${#display_archives[@]}): " choice </dev/tty
            if [[ "$choice" =~ ^[0-9]+$ ]]; then
                if [ "$choice" -eq 0 ]; then
                    read -p "Enter full path to archive file: " custom_path </dev/tty
                    if [ -f "$custom_path" ]; then
                        ARCHIVE_PATH="$custom_path"
                        break
                    else
                        print_error "Custom path file not found: $custom_path"
                    fi
                elif [ "$choice" -ge 1 ] && [ "$choice" -le ${#display_archives[@]} ]; then
                    ARCHIVE_PATH="${display_archives[$((choice-1))]}"
                    break
                else
                    print_error "Invalid choice. Please enter a number between 0 and ${#display_archives[@]}."
                fi
            else
                print_error "Invalid input. Please enter a number."
            fi
        done

        # Let the user know if they selected a source code version
        if [[ "$ARCHIVE_PATH" == *"-Unobf"* || "$ARCHIVE_PATH" == *"-unobf"* ]]; then
            print_step "Source code (unobfuscated) version selected: $ARCHIVE_PATH"
        else
             print_step "Selected archive: $ARCHIVE_PATH"
        fi
    else
        print_warning "No archives found automatically in common locations."
        while true; do
             read -p "Enter the full path to the product archive file: " custom_path </dev/tty
             if [ -f "$custom_path" ]; then
                 ARCHIVE_PATH="$custom_path"
                 break
             else
                 print_error "File not found: $custom_path. Please provide a valid path."
             fi
        done
    fi

    echo "Selected archive: $ARCHIVE_PATH" >> "$log_file"
    echo "Archive search completed: $(date)" >> "$log_file"
    echo "----------------------------------------" >> "$log_file"
}

#----- Extract Product -----#
extract_product() {
    local archive_path=$1
    local base_extract_path=$2 # e.g., /var/www/plex/plextickets
    local product_name=$(basename "$base_extract_path")

    # --- VERY FIRST THING: Print entry message ---
    # Ensure all informational output goes to stderr >&2
    echo "[DEBUG] Entered extract_product for '$product_name' with archive '$archive_path'" >&2

    print_step "Extracting product '$product_name' from $archive_path..." # Already goes to stderr

    # --- Pre-checks ---
    local temp_archive_path
    temp_archive_path=$(sudo mktemp --suffix=".$(basename "$archive_path" | sed 's/.*\.\(.*\)/\1/')") # Keep original extension
    if [ $? -ne 0 ] || [ -z "$temp_archive_path" ]; then
        print_error "Failed to create temporary file path for archive copy." # Already stderr
        return 1
    fi
    print_step "Copying archive to temporary location: $temp_archive_path" # Already stderr
    # Redirect cp errors to stderr if needed, but usually not necessary
    if ! sudo cp "$archive_path" "$temp_archive_path"; then
        print_error "Failed to copy archive from '$archive_path' to '$temp_archive_path'. Check source permissions." # Already stderr
        sudo rm -f "$temp_archive_path"
        return 1
    fi
    archive_path="$temp_archive_path"

    if [ ! -f "$archive_path" ]; then
        echo -e "\033[0;31m[DEBUG] Temporary archive file not found: '$archive_path'. Aborting extraction.\033[0m" >&2 # To stderr
        sudo rm -f "$archive_path"
        return 1
    fi

    print_step "Ensuring base directory exists: $base_extract_path" # Already stderr
    if [ -d "$base_extract_path" ]; then
        print_warning "Target directory $base_extract_path already exists. Clearing contents before extraction..." # Already stderr
        sudo rm -rf "${base_extract_path:?}"/*
        sudo rm -rf "${base_extract_path:?}"/.* 2>/dev/null # Redirect rm's own errors
    fi
    sudo mkdir -p "$base_extract_path"
    if ! check_command "Creating/Ensuring base extract directory '$base_extract_path'"; then
         echo -e "\033[0;31m[DEBUG] Failed to create base directory. Check permissions for /var/www/plex.\033[0m" >&2 # To stderr
         sudo rm -f "$archive_path"
         return 1
    fi
    if [ ! -d "$base_extract_path" ]; then
        echo -e "\033[0;31m[DEBUG] Base directory '$base_extract_path' still does not exist after mkdir.\033[0m" >&2 # To stderr
        sudo rm -f "$archive_path"
        return 1
    fi

    local extract_cmd=""
    local extract_status=1

    local temp_extract_dir
    print_step "Creating temporary directory for extraction..." # Already stderr
    local mktemp_status=0
    temp_extract_dir=$(sudo mktemp -d)
    mktemp_status=$?
    if [ $mktemp_status -ne 0 ] || [ -z "$temp_extract_dir" ] || [ ! -d "$temp_extract_dir" ]; then
         print_error "Failed to create temporary directory via mktemp (Status: $mktemp_status). Check /tmp permissions and space. Aborting." # Already stderr
         sudo rm -f "$archive_path"
         return 1
    fi
    print_step "Created temporary extraction directory: $temp_extract_dir" # Already stderr


    if [[ "$archive_path" =~ \.zip$ ]]; then
        check_command_exists "unzip" # Already stderr if fails
        print_step "Extracting zip to temporary location ($temp_extract_dir)..." # Already stderr
        # Let unzip output go to stderr for debugging
        sudo unzip -o "$archive_path" -d "$temp_extract_dir" >&2
        extract_status=$?
        extract_cmd="unzip"
    elif [[ "$archive_path" =~ \.rar$ ]]; then
        # ... (similar changes for unrar, ensuring its output goes to stderr) ...
        if ! command -v unrar &> /dev/null; then
            print_step "Attempting to install 'unrar'..." # Already stderr
            case $PKG_MANAGER in
                apt) sudo apt install -y unrar >&2 ;; # Redirect installer output
                dnf|yum) sudo $PKG_MANAGER install -y unrar >&2 ;;
                pacman) sudo pacman -S --noconfirm --needed unrar >&2 ;;
                zypper) sudo zypper install -y unrar >&2 ;;
                *) print_error "Cannot automatically install 'unrar'. Please install it manually."; sudo rm -rf "$temp_extract_dir"; sudo rm -f "$archive_path"; return 1 ;;
            esac
            check_command "unrar installation" || { sudo rm -rf "$temp_extract_dir"; sudo rm -f "$archive_path"; return 1; }
        fi
        print_step "Extracting rar to temporary location ($temp_extract_dir)..." # Already stderr
        # Let unrar output go to stderr
        sudo unrar x -o+ "$archive_path" "$temp_extract_dir/" >&2
        extract_status=$?
        extract_cmd="unrar"
    else
        print_error "Unsupported archive format: $archive_path (only .zip and .rar supported)" # Already stderr
        sudo rm -rf "$temp_extract_dir"
        sudo rm -f "$archive_path"
        return 1
    fi

    sudo rm -f "$archive_path"

    if [ $extract_status -ne 0 ]; then
        echo -e "\033[0;31m[DEBUG] Extraction command '$extract_cmd' failed with status $extract_status.\033[0m" >&2 # To stderr
        echo -e "\033[0;31m[DEBUG] Check archive integrity, read permissions, and disk space in '$temp_extract_dir'.\033[0m" >&2 # To stderr
        sudo rm -rf "$temp_extract_dir"
        return 1
    fi
    print_success "Archive extracted to temporary location." # Already stderr

    # --- Find the actual product directory within temp dir ---
    local source_path="$temp_extract_dir"
    local potential_subdir=""
    local subdirs=()
    # Use null delimiter for safety with find and read
    while IFS= read -d $'\0' -r dir; do
        # Ensure we only add non-empty directory paths
        if [ -n "$dir" ]; then
            subdirs+=("$dir")
        fi
    done < <(sudo find "$temp_extract_dir" -maxdepth 1 -mindepth 1 -type d -print0 2>/dev/null) # Redirect find errors

    # Safely get the count
    local num_subdirs=${#subdirs[@]}
    # Check for files safely
    local files_in_base
    files_in_base=$(sudo find "$temp_extract_dir" -maxdepth 1 -mindepth 1 -type f -print -quit 2>/dev/null) # Redirect find errors

    # Add debug output for counts
    echo "[DEBUG extract_product] Found $num_subdirs subdirectories in temp dir." >&2
    if [ -n "$files_in_base" ]; then
        echo "[DEBUG extract_product] Found files directly in temp dir base." >&2
    else
        echo "[DEBUG extract_product] No files found directly in temp dir base." >&2
    fi


    # --- Revised Logic ---
    local found_product_dir=false

    # 1. Check for a single subdirectory AND no files in the base
    # Ensure num_subdirs is treated as a number (default to 0 if empty)
    if [ "${num_subdirs:-0}" -eq 1 ] && [ -z "$files_in_base" ]; then
        potential_subdir="${subdirs[0]}"
        print_step "Detected single subdirectory '$(basename "$potential_subdir")' and no base files. Using its contents." >&2
        source_path="$potential_subdir"
        found_product_dir=true
    fi

    # 2. If not found yet, check for a subdirectory matching the product name (case-insensitive)
    if [ "$found_product_dir" = false ] && [ "${num_subdirs:-0}" -ge 1 ]; then
         for dir in "${subdirs[@]}"; do
             # Ensure dir is not empty before comparing
             if [ -n "$dir" ] && [[ "$(basename "$dir" | tr '[:upper:]' '[:lower:]')" == "$product_name" ]]; then
                 print_step "Detected subdirectory matching product name: '$(basename "$dir")'. Using its contents." >&2
                 source_path="$dir"
                 found_product_dir=true
                 break # Found the matching directory
             fi
         done
    fi

    # 3. If still not found, search for package.json (but prioritize matching/single dir)
    if [ "$found_product_dir" = false ]; then
         print_step "No single/matching subdir found, or files exist in base. Searching for package.json..." >&2
         local pkg_json_path
         # Search deeper (maxdepth 3) in case it's nested one level more
         pkg_json_path=$(sudo find "$temp_extract_dir" -maxdepth 3 -name 'package.json' -print -quit 2>/dev/null)
         if [ -n "$pkg_json_path" ]; then
             source_path=$(dirname "$pkg_json_path")
             print_step "Found package.json in '$source_path'. Using this directory's contents." >&2
             found_product_dir=true # Consider it found
         fi
    fi

    # 4. Final fallback / Warning
    if [ "$found_product_dir" = false ]; then
        print_warning "Could not reliably determine product root directory within archive." >&2
        print_warning "Using archive root '$source_path'. Installation might fail if this is incorrect." >&2
        # source_path remains $temp_extract_dir in this case
    fi

    print_step "Identified source path for moving: $source_path" >&2

    # --- Move files ---
    # The move command itself should be correct IF $source_path is correct.
    print_step "Moving extracted files from '$source_path' to '$base_extract_path'..." >&2
    local move_failed=false
    # Check if source_path actually exists and is a directory before trying to cd/mv
    if [ ! -d "$source_path" ]; then
        print_error "Identified source path '$source_path' is not a valid directory. Cannot move files." >&2
        move_failed=true
    elif [ -z "$(sudo ls -A "$source_path" 2>/dev/null)" ]; then
        print_warning "Source directory '$source_path' in temporary location appears empty. Nothing to move." >&2
    else
        # Move all contents (including hidden files/dirs like .git)
        # Use 'shopt -s dotglob' in a subshell to make * include hidden files
        # Then move everything from source_path into base_extract_path
        # Redirect mv output/errors to stderr
        if ! (cd "$source_path" && shopt -s dotglob && sudo mv -- * "$base_extract_path/" >&2); then
            local move_status=$?
            # Check if the target directory received *any* files/dirs
            if [ -z "$(sudo ls -A "$base_extract_path" 2>/dev/null)" ]; then
                 print_error "Failed to move files from '$source_path' to '$base_extract_path' (Exit Status: $move_status)." >&2
                 print_error "Target directory is empty. Check permissions and if source path was correct." >&2
                 move_failed=true
            else
                 # Check if the source directory still exists and is non-empty (partial move?)
                 if [ -d "$source_path" ] && [ -n "$(sudo ls -A "$source_path" 2>/dev/null)" ]; then
                     print_warning "Moving files reported an error (Exit Status: $move_status), and source directory '$source_path' still contains files. Move may be incomplete." >&2
                 else
                     print_warning "Moving files reported an error (Exit Status: $move_status), but target directory is not empty and source seems empty. Proceeding cautiously." >&2
                 fi
            fi
        fi
    fi

    if [ "$move_failed" = true ]; then
        sudo rm -rf "$temp_extract_dir"
        return 1
    fi
    print_success "File moving process completed." # Already stderr

    # --- Cleanup ---
    print_step "Cleaning up temporary extraction directory $temp_extract_dir..." # Already stderr
    sudo rm -rf "$temp_extract_dir"
    check_command "Temporary extraction directory cleanup" || return 1

    # --- Final Permissions ---
    print_step "Setting final permissions for $base_extract_path..." # Already stderr
    sudo chown -R root:root "$base_extract_path"
    check_command "Setting ownership to root for $base_extract_path" || return 1
    sudo find "$base_extract_path" -type d -exec chmod 755 {} \;
    check_command "Setting directory permissions (755)" || return 1
    sudo find "$base_extract_path" -type f -exec chmod 644 {} \;
    check_command "Setting file permissions (644)" || return 1

    # --- Final Sanity Check ---
    if [ ! -d "$base_extract_path" ]; then
        print_error "CRITICAL: Final check failed! Target directory '$base_extract_path' does not exist after extraction process." # Already stderr
        return 1
    fi
    if [ -z "$(sudo ls -A "$base_extract_path" 2>/dev/null)" ]; then
        print_warning "Final check: Target directory '$base_extract_path' appears empty after extraction process." # Already stderr
    fi

    print_success "Product extracted and prepared in: $base_extract_path" # Already stderr

    # ***** THIS is the ONLY echo that should go to STDOUT *****
    echo "$base_extract_path"

    return 0
}

install_npm_dependencies() {
    local product_path=$1

    print_step "Installing NPM dependencies in $product_path..."

    if [ ! -f "$product_path/package.json" ]; then
        print_error "No package.json found in $product_path. Cannot install dependencies."
        print_warning "Please ensure the archive was extracted correctly and contains a Node.js project."
        ls -la "$product_path" # Show directory contents for debugging
        return 1 # Failure
    fi

    print_step "Running 'npm install' as root..."
    # Use --unsafe-perm allows running scripts as root if needed. loglevel error reduces noise.
    if (cd "$product_path" && sudo npm install --unsafe-perm --loglevel error); then
         print_success "NPM dependencies installed successfully."
         # Permissions should be root:root already, no chown needed after
         return 0 # Success
    else
         print_error "Failed to install NPM dependencies."
         print_error "Please check the output above for errors."
         print_error "You may need to install build tools (like build-essential, python, make, g++) or run 'npm install' manually in '$product_path'."
         return 1 # Failure
    fi
}

#----- Generalized Product Installation Function -----#
install_product() {
    local product=$1
    local default_port=$2
    local has_dashboard=${3:-false} # Optional: true for PlexTickets dashboard

    print_header "Installing $product"

    # 1. Check if already installed (and offer removal)
    check_existing_installation "$product"

    # 2. Find the archive file
    find_archive_files "$product" # Sets global ARCHIVE_PATH

    # 3. Extract the product
    local base_path="$INSTALL_DIR/$product"
    local install_path # This will be set by the extract_product function

    # Call extract_product and capture its standard output (should ONLY be the path now)
    install_path=$(extract_product "$ARCHIVE_PATH" "$base_path")
    local extract_status=$? # Capture the return status of extract_product

    # --- Add Debugging ---
    # Use printf for safer output of potentially weird paths
    printf "[DEBUG install_product] Path captured: '%s'\n" "$install_path" >&2
    echo "[DEBUG install_product] Extraction status code: $extract_status" >&2
    # --- End Debugging ---

    # Check if extraction was successful (return status 0 and path is not empty)
    # No sanitization needed if extract_product behaves correctly
    if [ $extract_status -ne 0 ] || [ -z "$install_path" ]; then
        # Use printf here too
        printf "[DEBUG install_product] Product extraction failed (Status: %s, Path: '%s'). Aborting installation of %s.\n" "$extract_status" "$install_path" "$product" >&2
        print_error "Product extraction failed. See debug output above. Aborting installation of $product."
        exit 1
    fi

    # --- Add More Debugging ---
    printf "[DEBUG install_product] Checking directory existence for captured path: '%s'\n" "$install_path" >&2
    # Attempt to list the directory using the captured variable
    ls -ld "$install_path" >&2
    # --- End Debugging ---

    # Verify the directory actually exists after extraction using the captured path
    if [ ! -d "$install_path" ]; then
        # Use printf
        printf "[DEBUG install_product] Directory check failed for path: '%s'\n" "$install_path" >&2
        print_error "Extraction seemed successful, but the final directory '$install_path' was not found. Aborting."
        exit 1
    fi

    print_success "Product successfully prepared in: $install_path" # Already stderr

    # 4. Install NPM dependencies
    if ! install_npm_dependencies "$install_path"; then
        print_error "NPM dependency installation failed. Aborting installation of $product."
        # Clean up? Keep directory for manual troubleshooting.
        # sudo rm -rf "$install_path"
        exit 1
    fi

    # --- Conditional Web Setup ---
    # Only run web setup if it's NOT plextickets OR if it IS plextickets WITH the dashboard
    local port domain email skip_dns_check=false
    local needs_web_setup=true
    if [ "$product" == "plextickets" ] && [ "$has_dashboard" = false ]; then
        needs_web_setup=false
        print_step "Skipping web server configuration for PlexTickets (no dashboard)."
    fi

    if [ "$needs_web_setup" = true ]; then
        # 5. Configuration: Port, Domain, Email
        read -p "Enter port for $product (default: $default_port): " port </dev/tty
        port=${port:-$default_port}

        read -p "Enter domain/subdomain for $product (e.g., $product.example.com): " domain </dev/tty
        if [ -z "$domain" ]; then
            print_error "Domain cannot be empty. Aborting."
            exit 1
        fi

        read -p "Enter email address for SSL certificate renewal notices: " email </dev/tty
        if [ -z "$email" ]; then
            print_error "Email cannot be empty (required by Let's Encrypt). Aborting."
            exit 1
        fi

        # 6. Open Firewall Port
        open_port "$port" "$product"

        # 7. Check DNS
        if ! check_domain_dns "$domain"; then
            print_error "Domain DNS verification failed for $domain."
            read -p "Proceed with Nginx/SSL setup anyway? (y/n): " proceed_dns </dev/tty
            if [[ $proceed_dns != "y" && $proceed_dns != "Y" ]]; then
                print_error "Installation aborted due to DNS issues."
                exit 1
            else
                print_warning "Proceeding without proper DNS. Nginx/SSL setup might fail."
                skip_dns_check=true # Pass this to SSL setup? Certbot will fail anyway.
            fi
        fi

        # 8. Setup Nginx Reverse Proxy
        # Pass install_path for PlexStore 502 page root
        setup_nginx "$domain" "$port" "$product" "$install_path"

        # 9. Setup SSL Certificate
        setup_ssl "$domain" "$email" # Certbot handles DNS check internally too
    fi # End of conditional web setup

    # 10. Handle PlexTickets Dashboard Addon (Only if dashboard was requested initially)
    # This logic remains the same, as it's already conditional on $has_dashboard
    if [ "$product" == "plextickets" ] && [ "$has_dashboard" = true ]; then
        print_header "Installing PlexTickets Dashboard Addon"
        local dashboard_product="Dashboard" # Assuming addon archive name contains 'Dashboard'
        local dashboard_archive_path="" # Need to find this separately

        find_archive_files "$dashboard_product" # Sets global ARCHIVE_PATH again
        dashboard_archive_path="$ARCHIVE_PATH"

        local dashboard_base_path="$install_path/addons/dashboard" # Install into addons/dashboard subdir

        # Extract dashboard addon
        local dashboard_install_path
        dashboard_install_path=$(extract_product "$dashboard_archive_path" "$dashboard_base_path")
         if [ $? -ne 0 ] || [ -z "$dashboard_install_path" ] || [ ! -d "$dashboard_install_path" ]; then
            print_error "PlexTickets Dashboard extraction failed. Skipping dashboard setup."
            # Continue installing main product? Yes.
         else
            print_success "Dashboard addon extracted to: $dashboard_install_path"
            # Install dashboard NPM dependencies
            if ! install_npm_dependencies "$dashboard_install_path"; then
                print_error "Dashboard NPM dependency installation failed. Dashboard may not work."
            else
                 print_success "PlexTickets Dashboard addon installed successfully."
            fi
         fi
    fi


    # 11. Create Systemd Service (Always create the service)
    read -p "Set up '$product' to auto-start on boot using systemd? (y/n): " setup_startup </dev/tty
    if [[ $setup_startup == "y" || $setup_startup == "Y" ]]; then
        create_systemd_service "$product" "$install_path"
    else
        print_warning "Auto-start not configured. You will need to start it manually."
        print_step "To start manually (example): cd $install_path && sudo $NODE_EXECUTABLE ."
    fi

    # 12. Post-installation Steps
    print_success "$product installed successfully!"
    local config_file_path
    config_file_path=$(find "$install_path" -maxdepth 1 -name 'config.yml' -o -name 'config.yaml' -o -name 'config.json' | head -n 1)

    if [ -n "$config_file_path" ]; then
        print_step "Configuration file found at: $config_file_path"
        read -p "Do you want to edit the configuration file now? (y/n): " edit_config </dev/tty
        if [[ $edit_config == "y" || $edit_config == "Y" ]]; then
            check_command_exists "nano" # Or prompt for preferred editor? Nano is common.
            sudo nano "$config_file_path"
            print_step "If you made changes, restart the service: sudo systemctl restart plex-$product"
        fi
    else
        print_warning "Could not find a standard configuration file (config.yml, .yaml, .json) in $install_path."
        print_warning "Please configure the product manually according to its documentation."
    fi

    # Adjust final message based on whether web setup was done
    if [ "$needs_web_setup" = true ]; then
        echo -e "\n${GREEN}Access $product at: https://$domain${NC}"
    else
        echo -e "\n${GREEN}$product (bot only) installed. Configure it via its config file.${NC}"
    fi
    echo -e "${CYAN}Manage the service with: sudo systemctl [start|stop|restart|status] plex-$product${NC}"
    echo -e "${CYAN}View logs with: sudo journalctl -u plex-$product -f${NC}"
}


#----- Management Functions -----#

show_services_status() {
    print_header "Services Status"

    if [ ! -d "$INSTALL_DIR" ] || [ -z "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
        print_warning "No installations found in $INSTALL_DIR"
        return
    fi

    echo "+--------------+------------------+------+----------------------+"
    echo "| Product      | Service Status   | Port | Domain               |"
    echo "+--------------+------------------+------+----------------------+"

    # Find installed products by looking for directories
    local installed_products=()
    for potential_product_dir in "$INSTALL_DIR"/*/; do
         if [ -d "$potential_product_dir" ]; then
             local product_name=$(basename "$potential_product_dir")
             # Only list if it looks like a product dir (not 'backups')
             if [[ "$product_name" != "backups" ]]; then
                 installed_products+=("$product_name")
             fi
         fi
    done

    if [ ${#installed_products[@]} -eq 0 ]; then
         print_warning "No product directories found within $INSTALL_DIR"
         echo "+--------------+------------------+------+----------------------+"
         return
    fi


    for product in "${installed_products[@]}"; do
        service_name="plex-$product"
        status_text="Not Found"
        status_color=$RED
        port="N/A"
        domain="N/A"

        # Check systemd status
        if systemctl list-units --full -all | grep -q "$service_name.service"; then
            if systemctl is-active --quiet "$service_name"; then
                status_text="Active"
                status_color=$GREEN
            elif systemctl is-failed --quiet "$service_name"; then
                 status_text="Failed"
                 status_color=$RED
            else
                 status_text="Inactive"
                 status_color=$YELLOW
            fi
        else
             status_text="Not Installed"
             status_color=$RED
        fi


        # Get port and domain from nginx config if available
        local nginx_conf
        nginx_conf=$(grep -l "proxy_pass http://localhost:" "$NGINX_ENABLED"/*.conf "$NGINX_AVAILABLE"/*.conf 2>/dev/null | grep "$product" | head -n 1) # Heuristic search
        # More robust: Find config matching the service/install dir? Difficult.
        # Let's try finding by domain if possible, assuming domain includes product name
        nginx_conf=$(find "$NGINX_ENABLED/" "$NGINX_AVAILABLE/" -maxdepth 1 -name "*$product*.conf" -print -quit 2>/dev/null)


        if [ -f "$nginx_conf" ]; then
            domain=$(grep -m 1 "server_name" "$nginx_conf" | awk '{print $2}' | tr -d ';')
            port=$(grep -m 1 "proxy_pass http://localhost:" "$nginx_conf" | sed -n 's/.*localhost:\([0-9]*\).*/\1/p')
        fi
        # Fallback: Check config file if Nginx fails? Too complex for status overview.

        # Format with printf
        printf "| %-12s | ${status_color}%-16s${NC} | %-4s | %-20s |\n" "$product" "$status_text" "$port" "$domain"

    done
    echo "+--------------+------------------+------+----------------------+"
}

view_logs() {
    local product=$1
    local service_name="plex-$product"

    print_header "Viewing Logs for $product"

    if systemctl list-units --full -all | grep -q "$service_name.service"; then
        echo "Showing last 50 log entries for $service_name. Press Ctrl+C to stop following."
        echo "----------------------------------------"
        sudo journalctl -u "$service_name" -n 50 --no-pager -f
        echo "----------------------------------------"
    else
        print_error "Systemd service '$service_name' not found."
    fi
}

edit_configuration() {
     local product=$1
     local install_path="$INSTALL_DIR/$product"

     print_header "Editing Configuration for $product"

     if [ ! -d "$install_path" ]; then
         print_error "Installation directory not found: $install_path"
         return
     fi

     local config_file_path
     # Prioritize yml/yaml, then json
     config_file_path=$(find "$install_path" -maxdepth 1 \( -name 'config.yml' -o -name 'config.yaml' \) -print -quit)
     if [ -z "$config_file_path" ]; then
         config_file_path=$(find "$install_path" -maxdepth 1 -name 'config.json' -print -quit)
     fi
     # Add other common names if needed
     # if [ -z "$config_file_path" ]; then
     #     config_file_path=$(find "$install_path" -maxdepth 1 -name '.env' -print -quit)
     # fi

     if [ -n "$config_file_path" ] && [ -f "$config_file_path" ]; then
         print_step "Found configuration file: $config_file_path"
         check_command_exists "nano"
         sudo nano "$config_file_path"
         print_step "Configuration edited. Restart the service for changes to take effect:"
         print_step "sudo systemctl restart plex-$product"
     else
         print_warning "Could not find a standard configuration file (config.yml, .yaml, .json) in $install_path."
         print_step "You may need to edit the configuration manually based on the product's documentation."
         ls -la "$install_path" # Show files to help user find it
     fi
}

uninstall_product() {
    local product=$1
    local service_name="plex-$product"
    local install_path="$INSTALL_DIR/$product"
    local nginx_conf_file # Determined later

    print_header "Uninstalling $product"

    if [ ! -d "$install_path" ]; then
        print_warning "Installation directory $install_path not found. Cannot uninstall."
        return
    fi

    read -p "This will stop the service, remove systemd unit, remove Nginx config, and optionally delete all files in $install_path. Are you sure? (y/n): " confirm_uninstall </dev/tty
    if [[ $confirm_uninstall != "y" && $confirm_uninstall != "Y" ]]; then
        print_warning "Uninstallation cancelled."
        return
    fi

    # 1. Stop and disable the service
    print_step "Stopping service $service_name..."
    sudo systemctl stop "$service_name" &>/dev/null # Ignore error if not running
    if systemctl list-unit-files | grep -q "$service_name.service"; then
        print_step "Disabling service $service_name..."
        sudo systemctl disable "$service_name"
        check_command "Disabling service $service_name"
        print_step "Removing systemd service file..."
        sudo rm -f "/etc/systemd/system/$service_name.service"
        sudo rm -f "/etc/systemd/system/multi-user.target.wants/$service_name.service" # Remove symlink too
        check_command "Removing systemd files"
        print_step "Reloading systemd daemon..."
        sudo systemctl daemon-reload
        check_command "systemctl daemon-reload"
        print_success "Systemd service removed."
    else
        print_warning "Systemd service $service_name not found or already removed."
    fi

    # 2. Remove Nginx configuration
    print_step "Searching for Nginx configuration..."
    # Find config by domain (best guess) or proxy pass port (less reliable)
    local domain=""
    # Try finding domain from potential config file first
    local config_file_path=$(find "$install_path" -maxdepth 1 \( -name 'config.yml' -o -name 'config.yaml' -o -name 'config.json' \) -print -quit)
    if [ -f "$config_file_path" ]; then
        domain=$(grep -oiE '(domain|host):[[:space:]]+"?([a-zA-Z0-9.-]+)"?' "$config_file_path" | head -n 1 | sed -E 's/.*:[[:space:]]+"?([^"]+)"?/\1/')
    fi

    if [ -n "$domain" ]; then
         nginx_conf_file="$NGINX_AVAILABLE/$domain.conf"
         print_step "Found potential domain '$domain', checking Nginx config: $nginx_conf_file"
    else
         # Fallback: search for conf files containing the product name
         nginx_conf_file=$(find "$NGINX_AVAILABLE/" "$NGINX_ENABLED/" -maxdepth 1 -name "*$product*.conf" -print -quit 2>/dev/null)
         if [ -n "$nginx_conf_file" ]; then
             print_step "Found potential Nginx config by name: $nginx_conf_file"
         else
             print_warning "Could not automatically determine Nginx config file for $product."
             read -p "Enter the Nginx config filename in $NGINX_AVAILABLE (e.g., myapp.conf) or press Enter to skip: " manual_nginx_conf </dev/tty
             if [ -n "$manual_nginx_conf" ]; then
                 nginx_conf_file="$NGINX_AVAILABLE/$manual_nginx_conf"
             fi
         fi
    fi


    if [ -f "$nginx_conf_file" ]; then
        local nginx_base_name=$(basename "$nginx_conf_file")
        print_step "Removing Nginx site link: $NGINX_ENABLED/$nginx_base_name"
        sudo rm -f "$NGINX_ENABLED/$nginx_base_name"
        check_command "Removing Nginx enabled link"
        print_step "Removing Nginx available config: $nginx_conf_file"
        sudo rm -f "$nginx_conf_file"
        check_command "Removing Nginx available config"

        print_step "Testing Nginx configuration..."
        if sudo nginx -t; then
            print_step "Reloading Nginx..."
            sudo systemctl reload nginx
            check_command "Nginx reload"
            print_success "Nginx configuration removed."
        else
            print_error "Nginx configuration test failed after removing site. Please check manually ('sudo nginx -t')."
        fi
    else
        print_warning "Nginx configuration file not found or not specified. Skipping Nginx removal."
    fi

    # 3. Remove Installation Directory
    read -p "Do you want to permanently delete the installation directory '$install_path' and all its contents? (y/n): " delete_files </dev/tty
    if [[ $delete_files == "y" || $delete_files == "Y" ]]; then
        print_step "Deleting installation directory $install_path..."
        sudo rm -rf "$install_path"
        check_command "Deleting installation directory"
        print_success "Installation directory deleted."
    else
        print_warning "Installation directory $install_path was NOT deleted."
    fi

    # 4. SSL Certificate Info
    if [ -n "$domain" ]; then
        print_step "Checking for SSL certificate for domain '$domain'..."
        if sudo certbot certificates | grep -q "Domains: $domain"; then
            print_warning "An SSL certificate for '$domain' still exists."
            print_warning "You can remove it manually using:"
            print_warning "sudo certbot delete --cert-name $domain"
        else
             print_step "No active SSL certificate found for '$domain'."
        fi
    else
         print_warning "Could not determine domain. Check 'sudo certbot certificates' manually if you need to remove SSL certs."
    fi

    print_success "$product uninstallation process complete."

}


manage_installations() {
    local product_name

    # Get list of installed products
    local installed_products=()
    if [ -d "$INSTALL_DIR" ]; then
        for potential_product_dir in "$INSTALL_DIR"/*/; do
             if [ -d "$potential_product_dir" ]; then
                 local product=$(basename "$potential_product_dir")
                 # Check if a corresponding service exists for basic validation
                 if systemctl list-unit-files | grep -q "plex-$product.service"; then
                     # Exclude 'backups' directory
                     if [[ "$product" != "backups" ]]; then
                         installed_products+=("$product")
                     fi
                 fi
             fi
        done
    fi

    if [ ${#installed_products[@]} -eq 0 ]; then
        print_warning "No managed installations found (directory exists and has a systemd service)."
        return
    fi

    echo "Select product to manage:"
    local i=1
    for p in "${installed_products[@]}"; do
        echo "$i) $p"
        i=$((i+1))
    done
    echo "0) Back"

    read -p "Enter choice: " prod_choice </dev/tty
    if [[ "$prod_choice" =~ ^[0-9]+$ ]] && [ "$prod_choice" -ge 1 ] && [ "$prod_choice" -le ${#installed_products[@]} ]; then
        product_name="${installed_products[$((prod_choice-1))]}"
    elif [ "$prod_choice" -eq 0 ]; then
        return
    else
        print_error "Invalid choice."
        return
    fi

    local service_name="plex-$product_name"

    clear
    print_header "Manage: $product_name"
    echo "Service: $service_name"
    echo "Path: $INSTALL_DIR/$product_name"
    echo "---"
    sudo systemctl status "$service_name" --no-pager # Show current status
    echo "---"

    echo -e "${YELLOW}Management Options for $product_name:${NC}"
    echo -e "${CYAN}1) Start service${NC}"
    echo -e "${CYAN}2) Stop service${NC}"
    echo -e "${CYAN}3) Restart service${NC}"
    echo -e "${CYAN}4) Enable auto-start on boot${NC}"
    echo -e "${CYAN}5) Disable auto-start on boot${NC}"
    echo -e "${CYAN}6) View Logs (follow)${NC}"
    echo -e "${CYAN}7) Edit Configuration${NC}"
    echo -e "${RED}${BOLD}8) Uninstall $product_name${NC}"
    echo -e "${CYAN}0) Back to previous menu${NC}"

    read -p "Enter your choice for $product_name: " manage_choice </dev/tty

    case $manage_choice in
        1) print_step "Starting $service_name..."; sudo systemctl start "$service_name" ;;
        2) print_step "Stopping $service_name..."; sudo systemctl stop "$service_name" ;;
        3) print_step "Restarting $service_name..."; sudo systemctl restart "$service_name" ;;
        4) print_step "Enabling $service_name..."; sudo systemctl enable "$service_name" ;;
        5) print_step "Disabling $service_name..."; sudo systemctl disable "$service_name" ;;
        6) view_logs "$product_name" ;;
        7) edit_configuration "$product_name" ;;
        8) uninstall_product "$product_name" ;;
        0) return ;;
        *) print_error "Invalid choice" ;;
    esac

    # Show status again after action (except for logs/edit/uninstall/back)
    if [[ "$manage_choice" -ge 1 && "$manage_choice" -le 5 ]]; then
        print_step "Current status:"
        sudo systemctl status "$service_name" --no-pager
    fi
}


system_health_check() {
    print_header "System Health Check"

    # Check disk space for install dir mount point
    print_step "Checking disk space for $INSTALL_DIR..."
    local disk_usage
    disk_usage=$(df -h "$INSTALL_DIR" | awk 'NR==2 {print $5}' | tr -d '%')
    if [ -n "$disk_usage" ]; then
        if [ "$disk_usage" -gt 85 ]; then
            print_warning "Disk usage for $INSTALL_DIR partition is high: ${disk_usage}%"
        else
            print_success "Disk usage for $INSTALL_DIR partition is acceptable: ${disk_usage}%"
        fi
    else
        print_warning "Could not determine disk usage for $INSTALL_DIR."
    fi

    # Check memory
    print_step "Checking memory usage..."
    if command -v free &> /dev/null; then
        local memory_available_kb # Use MemAvailable if possible
        memory_available_kb=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
        local memory_free_kb=$(grep MemFree /proc/meminfo | awk '{print $2}')
        local memory_to_check_kb=${memory_available_kb:-$memory_free_kb} # Prefer Available, fallback Free
        local memory_to_check_mb=$((memory_to_check_kb / 1024))

        if [ "$memory_to_check_mb" -lt 250 ]; then # Lower threshold slightly
            print_warning "Low memory available/free: ${memory_to_check_mb} MB"
        else
            print_success "Memory available/free: ${memory_to_check_mb} MB"
        fi
    else
         print_warning "Could not check memory ('free' command not found)."
    fi


    # Check services status (using the status function)
    print_step "Checking Plex services status..."
    show_services_status # Reuse the detailed status display

    # Check Nginx service
    print_step "Checking Nginx service..."
    if systemctl is-active --quiet nginx; then
        print_success "Nginx service is active."
        if ! sudo nginx -t &>/dev/null; then
             print_warning "Nginx service is active, but configuration test failed ('nginx -t')."
        fi
    else
        print_warning "Nginx service is not active."
    fi

    # Check Certbot renewal timer/service
    print_step "Checking Certbot renewal timer..."
     if systemctl list-timers | grep -q 'certbot.timer'; then
         if systemctl is-active --quiet certbot.timer; then
              print_success "Certbot renewal timer (certbot.timer) is active."
         else
              print_warning "Certbot renewal timer (certbot.timer) is inactive."
         fi
     elif systemctl list-unit-files | grep -q 'certbot.service'; then
          print_warning "Found certbot.service but no certbot.timer. Automatic renewal might rely on cron or other methods."
     else
          print_warning "Could not find certbot.timer or certbot.service. Automatic SSL renewal might not be configured."
     fi


    # Check SSL certificates expiry
    print_step "Checking SSL certificate expiry dates..."
    if ! command -v openssl &> /dev/null; then
         print_warning "Cannot check SSL expiry ('openssl' command not found)."
    elif ! sudo certbot certificates &> /dev/null; then
         print_warning "Cannot check SSL expiry ('certbot' command failed or not configured)."
    else
        local cert_count=0
        # Use certbot certificates output for reliability
        sudo certbot certificates | grep -E '^\s+Certificate Name:|^\s+Domains:|^\s+Expiry Date:' | while read -r line; do
            if [[ $line == *"Certificate Name:"* ]]; then
                current_cert_name=$(echo "$line" | awk '{print $3}')
            elif [[ $line == *"Domains:"* ]]; then
                current_domains=$(echo "$line" | cut -d':' -f2- | xargs) # Trim whitespace
            elif [[ $line == *"Expiry Date:"* ]]; then
                cert_count=$((cert_count + 1))
                # Extract date and validity info
                expiry_info=$(echo "$line" | cut -d':' -f2-) # e.g., 2025-07-12 10:00:00+00:00 (VALID: 89 days)
                expiry_date=$(echo "$expiry_info" | sed -n 's/^\s*\([0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}\).*/\1/p')
                days_left_str=$(echo "$expiry_info" | sed -n 's/.*VALID: \([0-9]*\) days.*/\1/p')

                if [ -n "$days_left_str" ]; then
                    days_left=$((days_left_str)) # Convert to number
                    if [ "$days_left" -lt 15 ]; then
                        print_warning "SSL for '$current_cert_name' ($current_domains) expires in $days_left days ($expiry_date)."
                    elif [ "$days_left" -lt 30 ]; then
                         print_warning "SSL for '$current_cert_name' ($current_domains) expires in $days_left days ($expiry_date)." # Warning under 30 days
                    else
                        print_success "SSL for '$current_cert_name' ($current_domains) valid for $days_left days ($expiry_date)."
                    fi
                else
                    print_warning "Could not parse expiry days for '$current_cert_name' ($current_domains). Info: $expiry_info"
                fi
                # Reset for next cert block
                current_cert_name=""
                current_domains=""
            fi
        done
        if [ "$cert_count" -eq 0 ]; then
             print_step "No SSL certificates managed by Certbot found."
        fi
    fi
}


#----- Backup & Restore -----#
# Note: These functions operate directly on files and should still work.
# Ensure they use sudo appropriately as files are owned by root now.

backup_installation() {
    local product="$1"
    local install_path="$INSTALL_DIR/$product"

    if [ ! -d "$install_path" ]; then
        print_error "No installation found for $product at $install_path"
        return 1
    fi

    print_header "Backing up $product"

    local backup_dir="$INSTALL_DIR/backups" # Store backups within the main dir
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    local backup_file="$backup_dir/${product}_backup_$timestamp.tar.gz"

    # Create backup directory if it doesn't exist, owned by root
    sudo mkdir -p "$backup_dir"
    sudo chmod 700 "$backup_dir" # Restrict access
    check_command "Backup directory creation/permissioning"

    # Create backup using tar
    print_step "Creating backup archive: $backup_file..."
    # Run tar as root to ensure all files are read
    # Use -C to change directory so archive paths are relative
    if sudo tar -czf "$backup_file" -C "$INSTALL_DIR" "$product"; then
        print_success "Backup created successfully: $backup_file"
        sudo chmod 600 "$backup_file" # Restrict access to backup file
        # Optional: copy configs separately for easy access
        local config_file_path
        config_file_path=$(find "$install_path" -maxdepth 1 \( -name 'config.yml' -o -name 'config.yaml' -o -name 'config.json' \) -print -quit)
        if [ -f "$config_file_path" ]; then
            local config_backup_name="${product}_config_$timestamp.$(basename "$config_file_path" | sed 's/.*\.//')" # Get extension
            sudo cp "$config_file_path" "$backup_dir/$config_backup_name"
            sudo chmod 600 "$backup_dir/$config_backup_name"
            print_step "Configuration saved separately: $backup_dir/$config_backup_name"
        fi
        return 0
    else
        print_error "Failed to create backup archive."
        sudo rm -f "$backup_file" # Clean up failed attempt
        return 1
    fi
}

list_backups() {
    local backup_dir="$INSTALL_DIR/backups"

    print_header "Available Backups"

    if [ ! -d "$backup_dir" ] || [ -z "$(ls -A "$backup_dir"/*.tar.gz 2>/dev/null)" ]; then
        print_warning "No backups found in $backup_dir"
        return 1 # Indicate no backups
    fi

    echo "+----+---------------------+----------------+----------+"
    echo "| ID | Date                | Product        | Size     |"
    echo "+----+---------------------+----------------+----------+"

    local i=1
    local backups_found=() # Store paths for selection later
    # Use find to list files, sort by modification time (newest first)
    while IFS= read -r file; do
        backups_found+=("$file")
        local filename=$(basename "$file")
        # Try to parse date and product from filename (adjust regex if format changes)
        local date_part=$(echo "$filename" | grep -oE '[0-9]{8}_[0-9]{6}')
        local formatted_date="Unknown Date"
        if [ -n "$date_part" ]; then
             formatted_date=$(date -d "$(echo "$date_part" | sed 's/_/ /')" "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "$date_part")
        fi
        local product=$(echo "$filename" | sed -E 's/(_backup)?_[0-9]{8}_[0-9]{6}\.tar\.gz$//') # Extract product name
        local size=$(du -h "$file" | cut -f1)

        printf "| %-2s | %-19s | %-14s | %-8s |\n" "$i" "$formatted_date" "$product" "$size"
        i=$((i+1))
    done < <(find "$backup_dir" -maxdepth 1 -name "*.tar.gz" -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)

    echo "+----+---------------------+----------------+----------+"
    # Return the array of found backup paths indirectly via global var or direct echo? Echo is cleaner.
    # This function is just for listing, selection happens elsewhere.
    return 0 # Indicate backups were listed
}

restore_backup() {
    local backup_dir="$INSTALL_DIR/backups"

    print_header "Restore from Backup"

    # List backups and get paths
    local backups=()
    local i=1
    print_step "Finding available backups..."
     if ! list_backups; then # list_backups prints warning if none found
         return # Exit if no backups listed
     fi

    # Populate the backups array for selection (re-finding them)
    while IFS= read -r file; do
        backups+=("$file")
    done < <(find "$backup_dir" -maxdepth 1 -name "*.tar.gz" -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)


    read -p "Select backup ID to restore (1-${#backups[@]}): " choice </dev/tty
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#backups[@]} ]; then
        local selected_backup="${backups[$((choice-1))]}"
        local filename=$(basename "$selected_backup")
        # Extract product name from backup filename
        local product=$(echo "$filename" | sed -E 's/(_backup)?_[0-9]{8}_[0-9]{6}\.tar\.gz$//')
        local install_path="$INSTALL_DIR/$product"
        local service_name="plex-$product"

        print_warning "Restoring '$product' from '$filename'."
        print_warning "This will STOP the service (if running) and OVERWRITE the current installation at '$install_path'."
        read -p "Are you absolutely sure? (y/n): " confirm </dev/tty

        if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
            # 1. Stop the service
            if systemctl list-units --full -all | grep -q "$service_name.service"; then
                print_step "Stopping service $service_name..."
                sudo systemctl stop "$service_name" || print_warning "Failed to stop service (might not be running)."
            fi

            # 2. Remove existing installation directory (important!)
            if [ -d "$install_path" ]; then
                print_step "Removing existing installation directory $install_path..."
                sudo rm -rf "$install_path"
                check_command "Removing existing installation directory"
            fi

            # 3. Extract backup
            print_step "Extracting backup '$selected_backup' to '$INSTALL_DIR'..."
            # Use -C to extract into the target parent directory
            if sudo tar -xzf "$selected_backup" -C "$INSTALL_DIR"; then
                print_success "Backup extracted successfully."

                # 4. Fix permissions (critical after extracting as root)
                print_step "Setting permissions for restored files in $install_path..."
                if [ -d "$install_path" ]; then # Check if extraction actually created the dir
                    sudo chown -R root:root "$install_path" # Set to root:root
                    check_command "Setting ownership to root for $install_path"
                    sudo find "$install_path" -type d -exec chmod 755 {} \;
                    sudo find "$install_path" -type f -exec chmod 644 {} \;
                    print_success "Permissions set for restored files."
                else
                    print_error "Restored directory $install_path not found after extraction!"
                    return # Abort restore
                fi


                # 5. Restart the service
                if systemctl list-unit-files | grep -q "$service_name.service"; then
                    print_step "Starting service $service_name..."
                    if sudo systemctl start "$service_name"; then
                         print_success "Service $service_name started."
                    else
                         print_error "Service $service_name failed to start after restore."
                         print_error "Check logs: sudo journalctl -u $service_name -n 50"
                         print_error "Also check the restored configuration file."
                    fi
                else
                     print_warning "Service $service_name not found. Cannot start automatically."
                     print_step "You may need to run the installation for '$product' again to set up the service."
                fi

                print_success "Restore of '$product' complete."

            else
                print_error "Failed to extract backup file '$selected_backup'."
                print_warning "The installation directory $install_path may be missing or incomplete."
            fi
        else
            print_warning "Restore cancelled."
        fi
    else
        print_error "Invalid backup ID choice."
    fi
}

delete_backup() {
    local backup_dir="$INSTALL_DIR/backups"

    print_header "Delete Backup"

    # List backups and get paths
    local backups=()
    local i=1
    print_step "Finding available backups..."
    if ! list_backups; then # list_backups prints warning if none found
         return # Exit if no backups listed
     fi

    # Populate the backups array for selection (re-finding them)
    while IFS= read -r file; do
        backups+=("$file")
    done < <(find "$backup_dir" -maxdepth 1 -name "*.tar.gz" -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)

    read -p "Select backup ID to DELETE (1-${#backups[@]}): " choice </dev/tty
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#backups[@]} ]; then
        local selected_backup="${backups[$((choice-1))]}"
        local filename=$(basename "$selected_backup")

        print_warning "You are about to permanently delete the backup file:"
        print_warning "$filename"
        read -p "Are you absolutely sure? (y/n): " confirm </dev/tty
        if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
            print_step "Deleting backup file: $selected_backup"
            sudo rm -f "$selected_backup"
            if [ $? -eq 0 ]; then
                print_success "Backup file deleted successfully."
                # Also delete associated config backup if it exists
                local product=$(echo "$filename" | sed -E 's/(_backup)?_[0-9]{8}_[0-9]{6}\.tar\.gz$//')
                local timestamp=$(echo "$filename" | grep -oE '[0-9]{8}_[0-9]{6}')
                local config_backup_pattern="$backup_dir/${product}_config_${timestamp}.*"
                local config_backup_file=$(ls $config_backup_pattern 2>/dev/null | head -n 1)
                if [ -f "$config_backup_file" ]; then
                     print_step "Deleting associated config backup: $(basename "$config_backup_file")"
                     sudo rm -f "$config_backup_file"
                fi
            else
                print_error "Failed to delete backup file."
            fi
        else
            print_warning "Deletion cancelled."
        fi
    else
        print_error "Invalid backup ID choice."
    fi
}

manage_backups_menu() {
    while true; do
        clear
        print_header "Backup Management"
        echo "Backup Location: $INSTALL_DIR/backups"
        echo "---"

        echo -e "${YELLOW}Backup Options:${NC}"
        echo -e "${CYAN}1) Create backup of a product${NC}"
        echo -e "${CYAN}2) List available backups${NC}"
        echo -e "${CYAN}3) Restore product from backup${NC}"
        echo -e "${CYAN}4) Delete backup${NC}"
        echo -e "${CYAN}0) Return to Main Menu${NC}"

        read -p "Enter your choice: " backup_choice </dev/tty

        case $backup_choice in
            1)
                # Backup single product
                local installed_products=()
                if [ -d "$INSTALL_DIR" ]; then
                    for potential_product_dir in "$INSTALL_DIR"/*/; do
                         if [ -d "$potential_product_dir" ]; then
                             local product_name=$(basename "$potential_product_dir")
                             # Exclude 'backups' directory
                             if [[ "$product_name" != "backups" ]]; then
                                 installed_products+=("$product_name")
                             fi
                         fi
                    done
                fi
                if [ ${#installed_products[@]} -eq 0 ]; then
                    print_warning "No installed products found in $INSTALL_DIR to back up."
                else
                    echo "Select product to backup:"
                    local i=1
                    for p in "${installed_products[@]}"; do
                        echo "$i) $p"
                        i=$((i+1))
                    done
                    read -p "Enter choice (1-${#installed_products[@]}): " prod_choice </dev/tty
                    if [[ "$prod_choice" =~ ^[0-9]+$ ]] && [ "$prod_choice" -ge 1 ] && [ "$prod_choice" -le ${#installed_products[@]} ]; then
                        backup_installation "${installed_products[$((prod_choice-1))]}"
                    else
                        print_error "Invalid choice."
                    fi
                fi
                ;;
            2)
                list_backups
                ;;
            3)
                restore_backup
                ;;
            4)
                delete_backup
                ;;
            0)
                return # Exit this menu loop
                ;;
            *)
                print_error "Invalid choice."
                ;;
        esac

        # Pause after action before looping
        if [ "$backup_choice" != "0" ]; then
             read -p "Press Enter to continue..." </dev/tty
        fi
    done
}


#----- Main Script Logic -----#
main() {
    # Ensure script is run with root privileges for installs/management
    if [ "$(id -u)" -ne 0 ]; then
      print_error "This script requires root privileges. Please run with sudo."
      exit 1
    fi

    # Initial setup
    clear
    display_banner
    detect_system
    install_dependencies # Installs dependencies and verifies essential commands
    # setup_plex_user # REMOVED - No longer creating separate user

    # Create base install directory if it doesn't exist (owned by root)
    print_step "Ensuring base install directory '$INSTALL_DIR' exists..."
    sudo mkdir -p "$INSTALL_DIR"
    check_command "Base install directory creation"
    sudo chown root:root "$INSTALL_DIR" # Ensure root owns base dir
    sudo chmod 755 "$INSTALL_DIR"
    check_command "Base install directory permissions"

    # Main menu loop
    while true; do
        clear
        display_banner
        print_header "Main Menu"

        # Show quick status overview
        show_services_status
        echo "" # Add a newline

        echo -e "${YELLOW}Please select an option:${NC}"
        echo -e "${CYAN}1) Install PlexTickets${NC}"
        echo -e "${CYAN}2) Install PlexStaff${NC}"
        echo -e "${CYAN}3) Install PlexStatus${NC}"
        echo -e "${CYAN}4) Install PlexStore${NC}"
        echo -e "${CYAN}5) Install PlexForms${NC}"
        echo -e "----------------------------------------"
        echo -e "${CYAN}6) Manage Existing Installations${NC}"
        echo -e "${CYAN}7) Manage Backups${NC}"
        echo -e "${CYAN}8) System Health Check${NC}"
        echo -e "----------------------------------------"
        echo -e "${CYAN}0) Exit${NC}"

        read -p "Enter your choice: " choice </dev/tty

        case $choice in
            1) # Install PlexTickets
                read -p "Install PlexTickets Dashboard addon as well? (y/n): " dashboard_choice </dev/tty
                local install_dashboard=false
                if [[ $dashboard_choice == "y" || $dashboard_choice == "Y" ]]; then
                    install_dashboard=true
                fi
                install_product "plextickets" "3000" "$install_dashboard"
                ;;
            2) # Install PlexStaff
                install_product "plexstaff" "3001"
                ;;
            3) # Install PlexStatus
                install_product "plexstatus" "3002"
                ;;
            4) # Install PlexStore
                install_product "plexstore" "3003"
                ;;
            5) # Install PlexForms
                install_product "plexforms" "3004"
                ;;
            6) # Manage Installations
                manage_installations # This function now handles its own sub-menu loop
                ;;
            7) # Manage Backups
                manage_backups_menu # Use the dedicated backup menu function
                ;;
            8) # System Health Check
                system_health_check
                ;;
            0) # Exit
                print_success "Exiting PlexDevelopment Installer. Goodbye!"
                exit 0
                ;;
            *) # Invalid choice
                print_error "Invalid choice. Please try again."
                ;;
        esac

        # Pause after completing an action (except exit) before showing the main menu again
        if [ "$choice" != "0" ]; then
             read -p $'\nPress Enter to return to the main menu...' </dev/tty
        fi

    done # End of main menu loop
}

display_banner() {
    echo -e "${BOLD}${CYAN}"
    echo "  _____  _           _____                 _                                  _   "
    echo " |  __ \| |         |  __ \               | |                                | |  "
    echo " | |__) | | _____  _| |  | | _____   _____| | ___  _ __  _ __ ___   ___ _ __ | |_ "
    echo " |  ___/| |/ _ \ \/ / |  | |/ _ \ \ / / _ \ |/ _ \| '_ \| '_ \` _ \ / _ \ '_ \| __|"
    echo " | |    | |  __/>  <| |__| |  __/\ V /  __/ | (_) | |_) | | | | | |  __/ | | | |_ "
    echo " |_|    |_|\___/_/\_\_____/ \___| \_/ \___|_|\___/| .__/|_| |_| |_|\___|_| |_|\__|"
    echo "                                                  | |                             "
    echo "                                                  |_|                             "
    echo -e "${NC}"
    echo -e "${BOLD}${PURPLE}Installation Script for PlexDevelopment Products${NC}\n"
}

#--- Script Entry Point ---#
main "$@" # Pass any script arguments to main if needed in future
