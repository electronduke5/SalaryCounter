#!/bin/bash

# Telegram Salary Bot Deployment Script
# This script automates the deployment of the salary bot with systemd service

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
BOT_NAME="salary-bot"
BOT_DIR="$(pwd)"
SERVICE_NAME="${BOT_NAME}.service"
VENV_DIR="${BOT_DIR}/venv"
USER=$(whoami)

echo -e "${BLUE}🤖 Starting Telegram Salary Bot deployment...${NC}"

# Function to print colored output
print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check if running as root
check_permissions() {
    if [[ $EUID -eq 0 ]]; then
        print_warning "Running as root. This is not recommended for security reasons."
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

# Install system dependencies
install_system_deps() {
    echo -e "${BLUE}📦 Checking system dependencies...${NC}"
    
    # Update package list
    if command -v apt-get &> /dev/null; then
        sudo apt-get update -qq
        
        # Install Python3 if not present
        if ! command -v python3 &> /dev/null; then
            print_status "Installing Python3..."
            sudo apt-get install -y python3
        else
            print_status "Python3 is already installed"
        fi
        
        # Install pip if not present
        if ! command -v pip3 &> /dev/null && ! python3 -m pip --version &> /dev/null; then
            print_status "Installing pip..."
            sudo apt-get install -y python3-pip
        else
            print_status "pip is already installed"
        fi
        
        # Install venv if not present
        if ! python3 -c "import venv" &> /dev/null; then
            print_status "Installing python3-venv..."
            sudo apt-get install -y python3-venv
        else
            print_status "python3-venv is already installed"
        fi
        
    elif command -v yum &> /dev/null; then
        # CentOS/RHEL
        if ! command -v python3 &> /dev/null; then
            print_status "Installing Python3..."
            sudo yum install -y python3
        fi
        
        if ! command -v pip3 &> /dev/null; then
            print_status "Installing pip..."
            sudo yum install -y python3-pip
        fi
        
    else
        print_error "Unsupported package manager. Please install Python3 and pip manually."
        exit 1
    fi
}

# Create virtual environment
setup_venv() {
    echo -e "${BLUE}🐍 Setting up virtual environment...${NC}"
    
    if [ -d "$VENV_DIR" ]; then
        print_warning "Virtual environment already exists. Removing old one..."
        rm -rf "$VENV_DIR"
    fi
    
    python3 -m venv "$VENV_DIR"
    print_status "Virtual environment created"
    
    # Activate virtual environment
    source "$VENV_DIR/bin/activate"
    
    # Upgrade pip
    pip install --upgrade pip
    print_status "pip upgraded"
    
    # Install requirements
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
        print_status "Dependencies installed from requirements.txt"
    else
        print_error "requirements.txt not found!"
        exit 1
    fi
}

# Create .env file if it doesn't exist
setup_env() {
    echo -e "${BLUE}🔐 Setting up environment variables...${NC}"
    
    if [ ! -f ".env" ]; then
        cat > .env << EOF
# Telegram Bot Token
# Get it from @BotFather on Telegram
BOT_TOKEN=your_bot_token_here
EOF
        print_warning ".env file created. Please edit it and add your BOT_TOKEN!"
        print_warning "You can get the token from @BotFather on Telegram"
    else
        print_status ".env file already exists"
    fi
}

# Create systemd service file
create_service() {
    echo -e "${BLUE}⚙️  Creating systemd service...${NC}"
    
    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"
    
    sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Telegram Salary Bot
After=network.target
Wants=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$BOT_DIR
Environment=PATH=$VENV_DIR/bin
ExecStart=$VENV_DIR/bin/python main.py
EnvironmentFile=$BOT_DIR/.env
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$BOT_NAME

[Install]
WantedBy=multi-user.target
EOF
    
    print_status "Service file created at $SERVICE_FILE"
}

# Enable and start service
start_service() {
    echo -e "${BLUE}🚀 Starting service...${NC}"
    
    # Reload systemd
    sudo systemctl daemon-reload
    print_status "Systemd configuration reloaded"
    
    # Enable service
    sudo systemctl enable "$SERVICE_NAME"
    print_status "Service enabled for autostart"
    
    # Check if BOT_TOKEN is set
    if grep -q "your_bot_token_here" .env 2>/dev/null; then
        print_warning "BOT_TOKEN is not set in .env file!"
        print_warning "Please edit .env file and add your bot token, then run:"
        print_warning "sudo systemctl start $SERVICE_NAME"
        return
    fi
    
    # Start service
    sudo systemctl start "$SERVICE_NAME"
    
    # Check service status
    sleep 2
    if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        print_status "Service started successfully!"
    else
        print_error "Service failed to start. Check logs with: sudo journalctl -u $SERVICE_NAME -f"
        exit 1
    fi
}

# Show service management commands
show_commands() {
    echo -e "${BLUE}📋 Service Management Commands:${NC}"
    echo "Start service:    sudo systemctl start $SERVICE_NAME"
    echo "Stop service:     sudo systemctl stop $SERVICE_NAME"
    echo "Restart service:  sudo systemctl restart $SERVICE_NAME"
    echo "Service status:   sudo systemctl status $SERVICE_NAME"
    echo "View logs:        sudo journalctl -u $SERVICE_NAME -f"
    echo "Disable service:  sudo systemctl disable $SERVICE_NAME"
    echo ""
    echo -e "${BLUE}📁 Project files:${NC}"
    echo "Bot directory:    $BOT_DIR"
    echo "Virtual env:      $VENV_DIR"
    echo "Service file:     /etc/systemd/system/$SERVICE_NAME"
    echo "Environment:      $BOT_DIR/.env"
}

# Main deployment function
main() {
    echo -e "${BLUE}Starting deployment in directory: $BOT_DIR${NC}"
    
    # Check permissions
    check_permissions
    
    # Install system dependencies
    install_system_deps
    
    # Setup virtual environment
    setup_venv
    
    # Setup environment variables
    setup_env
    
    # Create systemd service
    create_service
    
    # Start service
    start_service
    
    # Show management commands
    echo ""
    print_status "Deployment completed successfully! 🎉"
    echo ""
    show_commands
}

# Run main function
main "$@"