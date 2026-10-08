#!/usr/bin/env bash
# ==============================================================================
# NewAgent CMS: MODULAR LAUNCHER
# PURPOSE: Ensure only ONE service runs at a time for maximum RAM efficiency.
# STRIP NOTE: Page Editor V1/V2 and the Profile Manager (Persona Hub) were
# removed as part of the NewAgent CMS fork -- only Admin and Publisher remain.
# ==============================================================================

get_script_path() {
    local source="${BASH_SOURCE[0]}"
    while [ -h "$source" ]; do
        local dir="$( cd -P "$( dirname "$source" )" >/dev/null 2>&1 && pwd )"
        source="$(readlink "$source")"
        [[ $source != /* ]] && source="$dir/$source"
    done
    echo "$( cd -P "$( dirname "$source" )" >/dev/null 2>&1 && pwd )"
}
SCRIPT_PATH=$(get_script_path)
WEB_DIR="$SCRIPT_PATH/src/web"
LOG_DIR="$SCRIPT_PATH/storage/tmp/logs"
mkdir -p "$LOG_DIR"

# Colors
C_RED='\033[1;31m'
C_GREEN='\033[1;32m'
C_CYAN='\033[1;36m'
C_YELLOW='\033[1;33m'
C_RESET='\033[0m'

function kill_services() {
    echo -e "${C_CYAN}[System] Stopping all active CMS services to free RAM...${C_RESET}"
    pkill -f "NewAgent_CMS_Admin.py" 2>/dev/null
    pkill -f "NewAgent_CMS_Publisher.py" 2>/dev/null
    sleep 1
}

function launch_service() {
    local script_name=$1
    local port=$2
    local log_file="$LOG_DIR/${script_name}.log"

    # 1. Kill everything else first
    kill_services

    # 2. Launch the requested service
    echo -e "${C_GREEN}[System] Bootstrapping $script_name on port $port...${C_RESET}"
    echo -e "${C_YELLOW}[System] Logging output to: $log_file${C_RESET}"
    echo "--------------------------------------------------------"

    # Run the script, capturing output to the terminal AND saving it to the log file
    python3 "$WEB_DIR/$script_name" 2>&1 | tee "$log_file"

    # Capture the exit code of the python script (not the tee command)
    local exit_code=${PIPESTATUS[0]}

    echo "--------------------------------------------------------"
    if [ $exit_code -ne 0 ]; then
        echo -e "${C_RED}[CRITICAL] $script_name crashed with exit code $exit_code!${C_RESET}"
        echo -e "${C_YELLOW}Review the traceback above. A full log has been saved to: $log_file${C_RESET}"
    else
        echo -e "${C_CYAN}[System] Service stopped normally.${C_RESET}"
    fi

    # 3. Force the menu to wait so you can actually read the error
    echo ""
    read -p "Press [Enter] to return to the menu..."
}

while true; do
    clear
    echo "========================================================"
    echo -e " ${C_RED}NEWAGENT CMS: MODULAR LAUNCHER${C_RESET}"
    echo "========================================================"
    echo " RAM-Optimized Mode: Only ONE service runs at a time."
    echo ""
    echo "  1) Launch Admin (Dashboard)              [Port 5001]"
    echo "  2) Launch Static Site Publisher           [Port 5001]"
    echo ""
    echo "  4) Advanced Launcher (persistent, multi-service, PID-tracked)"
    echo "  3) Stop All Services & Exit"
    echo "========================================================"
    read -p " Select an option (1-4): " choice

    case $choice in
        1) launch_service "NewAgent_CMS_Admin.py" "5001" ;;
        2) launch_service "NewAgent_CMS_Publisher.py" "5001" ;;
        4)
            # Advanced menu allows multiple services at once, so this
            # RAM-optimized launcher's default kill-everything-first
            # behavior does NOT apply once you're inside it.
            python3 "$SCRIPT_PATH/advanced_launcher.py"
            ;;
        3)
            kill_services
            echo -e "${C_GREEN}[System] All CMS services stopped. Exiting.${C_RESET}"
            exit 0
            ;;
        *)
            echo -e "${C_RED}[Error] Invalid selection. Please choose 1-4.${C_RESET}"
            sleep 2
            ;;
    esac
done
