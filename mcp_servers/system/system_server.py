#!/usr/bin/env python3
"""
System Health Monitor for LLM Intent Function
Provides comprehensive system statistics and alerts for a Linux box
running llama.cpp, XTTS, ComfyUI, and PostgreSQL
"""

import psutil
import shutil
import subprocess
import json
from typing import Dict, List, Any
from dataclasses import dataclass, asdict
import logging
import sys
from pathlib import Path
from typing import Dict, Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_servers.base.base_server import IrisMCPServer

@dataclass
class DriveInfo:
    device: str
    mountpoint: str
    total_gb: float
    used_gb: float
    free_gb: float
    usage_percent: float
    filesystem: str

@dataclass
class GPUInfo:
    index: int
    name: str
    total_vram_mb: int
    used_vram_mb: int
    free_vram_mb: int
    usage_percent: float
    temperature_c: int
    power_draw_w: int
    utilization_percent: int

@dataclass
class SystemHealth:
    drives: List[DriveInfo]
    ram: Dict[str, Any]
    gpus: List[GPUInfo]
    cpu: Dict[str, Any]
    processes: Dict[str, Any]
    alerts: List[str]
    timestamp: str


server = IrisMCPServer(
    name="Iris system Server",
    description="System data server - CPU, Ram, Temps, etc..."
)


@server.register_tool
def get_drive_statistics() -> List[DriveInfo]:
    """Get disk usage statistics for all mounted drives."""
    drives = []
    partitions = psutil.disk_partitions()
    
    for partition in partitions:
        # Skip snap mounts and other virtual filesystems
        if any(skip in partition.mountpoint for skip in ['/snap/', '/dev/', '/proc/', '/sys/', '/run/']):
            continue
        
        # Skip if filesystem type suggests it's virtual
        if partition.fstype in ['squashfs', 'tmpfs', 'devtmpfs', 'sysfs', 'proc', 'devpts']:
            continue
            
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            # Skip very small drives (less than 100MB total)
            if usage.total < 100 * 1024 * 1024:
                continue
                
            drive_info = DriveInfo(
                device=partition.device,
                mountpoint=partition.mountpoint,
                total_gb=round(usage.total / (1024**3), 2),
                used_gb=round(usage.used / (1024**3), 2),
                free_gb=round(usage.free / (1024**3), 2),
                usage_percent=round((usage.used / usage.total) * 100, 1),
                filesystem=partition.fstype
            )
            drives.append(drive_info)
        except (PermissionError, OSError):
            # Skip drives we can't access
            continue
    
    return drives

@server.register_tool
def get_ram_statistics() -> Dict[str, Any]:
    """Get RAM usage statistics."""
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    
    return {
        'total_gb': round(memory.total / (1024**3), 2),
        'available_gb': round(memory.available / (1024**3), 2),
        'used_gb': round(memory.used / (1024**3), 2),
        'usage_percent': memory.percent,
        'swap_total_gb': round(swap.total / (1024**3), 2),
        'swap_used_gb': round(swap.used / (1024**3), 2),
        'swap_percent': swap.percent
    }

@server.register_tool
def get_nvidia_gpu_statistics() -> List[GPUInfo]:
    """Get NVIDIA GPU statistics using nvidia-ml-py or nvidia-smi."""
    gpus = []
    
    try:
        # Try using nvidia-ml-py first (more efficient)
        import pynvml
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            # Handle both bytes and string returns from different pynvml versions
            if isinstance(name, bytes):
                name = name.decode('utf-8')
            
            # Memory info
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            
            # Temperature
            try:
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except:
                temp = 0
            
            # Power draw
            try:
                power = pynvml.nvmlDeviceGetPowerUsage(handle) // 1000  # Convert mW to W
            except:
                power = 0
            
            # Utilization
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpu_util = util.gpu
            except:
                gpu_util = 0
            
            gpu_info = GPUInfo(
                index=i,
                name=name,
                total_vram_mb=mem_info.total // (1024**2),
                used_vram_mb=mem_info.used // (1024**2),
                free_vram_mb=mem_info.free // (1024**2),
                usage_percent=round((mem_info.used / mem_info.total) * 100, 1),
                temperature_c=temp,
                power_draw_w=power,
                utilization_percent=gpu_util
            )
            gpus.append(gpu_info)
            
    except (ImportError, Exception) as e:
        # Fallback to nvidia-smi command if pynvml fails
        try:
            result = subprocess.run([
                'nvidia-smi', '--query-gpu=index,name,memory.total,memory.used,memory.free,temperature.gpu,power.draw,utilization.gpu',
                '--format=csv,noheader,nounits'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if line.strip():
                        parts = [p.strip() for p in line.split(',')]
                        if len(parts) >= 6:
                            total_mb = int(parts[2]) if parts[2] != 'N/A' else 0
                            used_mb = int(parts[3]) if parts[3] != 'N/A' else 0
                            free_mb = int(parts[4]) if parts[4] != 'N/A' else 0
                            temp = int(parts[5]) if parts[5] != 'N/A' else 0
                            power = int(float(parts[6])) if len(parts) > 6 and parts[6] != 'N/A' else 0
                            util = int(parts[7]) if len(parts) > 7 and parts[7] != 'N/A' else 0
                            
                            gpu_info = GPUInfo(
                                index=int(parts[0]),
                                name=parts[1],
                                total_vram_mb=total_mb,
                                used_vram_mb=used_mb,
                                free_vram_mb=free_mb,
                                usage_percent=round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0,
                                temperature_c=temp,
                                power_draw_w=power,
                                utilization_percent=util
                            )
                            gpus.append(gpu_info)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError, Exception):
            pass
    
    return gpus

@server.register_tool
def get_cpu_statistics() -> Dict[str, Any]:
    """Get CPU usage statistics."""
    cpu_percent = psutil.cpu_percent(interval=1, percpu=True)
    cpu_freq = psutil.cpu_freq()
    load_avg = psutil.getloadavg()
    
    return {
        'usage_percent': round(psutil.cpu_percent(), 1),
        'usage_per_core': [round(p, 1) for p in cpu_percent],
        'core_count': psutil.cpu_count(),
        'load_average_1m': round(load_avg[0], 2),
        'load_average_5m': round(load_avg[1], 2),
        'load_average_15m': round(load_avg[2], 2),
        'frequency_mhz': round(cpu_freq.current, 0) if cpu_freq else 0
    }

@server.register_tool
def get_process_statistics() -> Dict[str, Any]:
    """Get statistics for key processes (llama.cpp, XTTS, ComfyUI, PostgreSQL)."""
    process_stats = {
        'llama_cpp': [],
        'xtts': [],
        'comfyui': [],
        'postgresql': [],
        'other_python': []
    }
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_percent', 'cpu_percent']):
        try:
            info = proc.info
            if not info['cmdline']:
                continue
                
            cmdline = ' '.join(info['cmdline']).lower()
            name_lower = info['name'].lower()
            
            proc_data = {
                'pid': info['pid'],
                'name': info['name'],
                'memory_percent': round(info['memory_percent'], 1),
                'cpu_percent': round(info['cpu_percent'], 1)
            }
            
            # More comprehensive process detection
            if any(keyword in cmdline for keyword in ['llama', 'llamacpp', 'llama.cpp']) or 'llama' in name_lower:
                process_stats['llama_cpp'].append(proc_data)
            elif any(keyword in cmdline for keyword in ['xtts', 'tts', 'coqui']) or 'xtts' in name_lower:
                process_stats['xtts'].append(proc_data)
            elif any(keyword in cmdline for keyword in ['comfyui', 'comfy']) or 'comfy' in name_lower:
                process_stats['comfyui'].append(proc_data)
            elif any(keyword in cmdline for keyword in ['postgres', 'postgresql']) or name_lower in ['postgres', 'postgresql']:
                process_stats['postgresql'].append(proc_data)
            elif info['name'] == 'python' or info['name'] == 'python3':
                # Check for common server/application patterns in Python processes
                if any(keyword in cmdline for keyword in ['server.py', 'main.py', 'app.py', 'run.py', 'serve', 'gradio', 'flask', 'fastapi', 'streamlit']):
                    process_stats['other_python'].append(proc_data)
                
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, TypeError):
            continue
    
    return process_stats

@server.register_tool
def generate_alerts(drives: List[DriveInfo], ram: Dict[str, Any], gpus: List[GPUInfo], cpu: Dict[str, Any]) -> List[str]:
    """Generate system health alerts based on thresholds."""
    alerts = []
    
    # Drive space alerts
    for drive in drives:
        if drive.usage_percent > 90:
            alerts.append(f"CRITICAL: Drive {drive.mountpoint} is {drive.usage_percent}% full ({drive.free_gb}GB free)")
        elif drive.usage_percent > 80:
            alerts.append(f"WARNING: Drive {drive.mountpoint} is {drive.usage_percent}% full ({drive.free_gb}GB free)")
    
    # RAM alerts
    if ram['usage_percent'] > 90:
        alerts.append(f"CRITICAL: RAM usage at {ram['usage_percent']}% ({ram['available_gb']}GB available)")
    elif ram['usage_percent'] > 80:
        alerts.append(f"WARNING: High RAM usage at {ram['usage_percent']}% ({ram['available_gb']}GB available)")
    
    # Swap alerts
    if ram['swap_percent'] > 50:
        alerts.append(f"WARNING: Swap usage at {ram['swap_percent']}%")
    
    # GPU alerts
    for gpu in gpus:
        if gpu.usage_percent > 95:
            alerts.append(f"CRITICAL: GPU {gpu.index} ({gpu.name}) VRAM at {gpu.usage_percent}% ({gpu.free_vram_mb}MB free)")
        elif gpu.usage_percent > 85:
            alerts.append(f"WARNING: GPU {gpu.index} ({gpu.name}) VRAM at {gpu.usage_percent}% ({gpu.free_vram_mb}MB free)")
        
        if gpu.temperature_c > 85:
            alerts.append(f"WARNING: GPU {gpu.index} temperature high: {gpu.temperature_c}°C")
        elif gpu.temperature_c > 90:
            alerts.append(f"CRITICAL: GPU {gpu.index} temperature critical: {gpu.temperature_c}°C")
    
    # CPU alerts
    if cpu['usage_percent'] > 90:
        alerts.append(f"WARNING: High CPU usage at {cpu['usage_percent']}%")
    
    if cpu['load_average_5m'] > cpu['core_count'] * 2:
        alerts.append(f"WARNING: High load average: {cpu['load_average_5m']} (cores: {cpu['core_count']})")
    
    return alerts

@server.register_tool
def get_system_health_statistics() -> Dict[str, Any]:
    """
    Main function to get comprehensive system health statistics.
    
    Returns a dictionary with all system statistics and alerts.
    """
    import datetime
    
    try:
        drives = get_drive_statistics()
        ram = get_ram_statistics()
        gpus = get_nvidia_gpu_statistics()
        cpu = get_cpu_statistics()
        processes = get_process_statistics()
        alerts = generate_alerts(drives, ram, gpus, cpu)
        success = "\"Success\": True "

        health = SystemHealth(
            drives=drives,
            ram=ram,
            gpus=gpus,
            cpu=cpu,
            processes=processes,
            alerts=alerts,
            timestamp=datetime.datetime.now().isoformat()
        )
        
        prep =  asdict(health)
        prep = {"success": True, **prep}
        return(prep)

        
    except Exception as e:
        logging.error(f"Error getting system health statistics: {e}")
        return {
            'error': str(e),
            'timestamp': datetime.datetime.now().isoformat()
        }

@server.register_tool
def format_system_health_summary(stats: Dict[str, Any]) -> str:
    """
    Format system health statistics into a human-readable summary.
    Perfect for LLM consumption.
    """
    if 'error' in stats:
        return f"System health check failed: {stats['error']}"
    
    summary = []
    summary.append("=== SYSTEM HEALTH REPORT ===")
    summary.append(f"Timestamp: {stats['timestamp']}")
    
    # Alerts first
    if stats['alerts']:
        summary.append("\n🚨 ALERTS:")
        for alert in stats['alerts']:
            summary.append(f"  • {alert}")
    else:
        summary.append("\n✅ No critical alerts")
    
    # Storage
    summary.append("\n💾 STORAGE:")
    for drive in stats['drives']:
        summary.append(f"  {drive['mountpoint']}: {drive['free_gb']}GB free of {drive['total_gb']}GB ({drive['usage_percent']}% used)")
    
    # Memory
    ram = stats['ram']
    summary.append(f"\n🧠 MEMORY:")
    summary.append(f"  RAM: {ram['available_gb']}GB available of {ram['total_gb']}GB ({ram['usage_percent']}% used)")
    if ram['swap_total_gb'] > 0:
        summary.append(f"  Swap: {ram['swap_percent']}% used")
    
    # GPUs
    if stats['gpus']:
        summary.append(f"\n🎮 GPUs:")
        for gpu in stats['gpus']:
            summary.append(f"  GPU {gpu['index']} ({gpu['name']}): {gpu['free_vram_mb']}MB VRAM free of {gpu['total_vram_mb']}MB ({gpu['usage_percent']}% used, {gpu['temperature_c']}°C)")
    else:
        summary.append(f"\n🎮 No NVIDIA GPUs detected")
    
    # CPU
    cpu = stats['cpu']
    summary.append(f"\n⚡ CPU: {cpu['usage_percent']}% usage, Load: {cpu['load_average_1m']}/{cpu['load_average_5m']}/{cpu['load_average_15m']}")
    
    # Key processes
    processes = stats['processes']
    active_services = []
    for service, procs in processes.items():
        if procs:
            active_services.append(f"{service} ({len(procs)} processes)")
    
    if active_services:
        summary.append(f"\n🔧 ACTIVE SERVICES: {', '.join(active_services)}")
    
    return '\n'.join(summary)

@server.register_tool
def system_status_summary():
     health_stats = get_system_health_statistics()
     return (format_system_health_summary(health_stats))



import subprocess
import json
import os
from datetime import datetime

import subprocess
import re



@server.register_tool
def linux_shell(command: str) -> dict:
    """
    Execute shell commands for Iris with reasonable safety guardrails.
    Iris is a trusted autonomous agent - we protect against accidents, not malice.
    
    Args:
        command: Shell command to execute
        
    Returns:
        dict with success, output, and error fields
    """
    
    # Only block truly catastrophic commands
    HARD_BLOCKS = {
        "sudo", "su", "doas",                    # Privilege escalation
        "reboot", "shutdown", "halt", "poweroff", # System control
        "mkfs", "fdisk", "parted",               # Disk formatting
        "iptables", "ufw", "firewall-cmd",       # Firewall changes
        "useradd", "userdel", "usermod",         # User management
        "systemctl stop", "systemctl disable",   # Don't let her kill services
    }
    
    # Check for hard blocks
    if not command or not command.strip():
        return {"success": False, "error": "Empty command"}
    
    # Check if command starts with a blocked command
    cmd_start = command.strip().split()[0]
    if cmd_start in HARD_BLOCKS:
        return {"success": False, "error": f"Command '{cmd_start}' is blocked for system safety"}
    
    # Block systemctl stop/disable specifically
    if "systemctl" in command and ("stop" in command or "disable" in command):
        return {"success": False, "error": "Cannot stop or disable system services"}
    
    # Block rm -rf / (catastrophic deletion)
    if "rm" in command and ("-rf" in command or "-fr" in command):
        if " / " in command or command.endswith(" /"):
            return {"success": False, "error": "Recursive deletion of root directory blocked"}
    
    # Everything else? Trust Iris.
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,  # Longer timeout for complex operations
            executable="/bin/bash",
            cwd="/iris-v3"
        )
        
        return {
            "success": True,
            "output": result.stdout.strip(),
            "error": result.stderr.strip() if result.stderr else None
        }
    
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Command timed out after 60 seconds"
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": f"Error executing command: {str(e)}"
        }
    
    # ========== VALIDATION FUNCTIONS ==========
    
    def validate_pipes(cmd):
        """Validate that pipe usage is safe"""
        if "|" not in cmd:
            return True, None
        
        # Split by pipe
        pipe_parts = cmd.split("|")
        
        for i, part in enumerate(pipe_parts):
            part = part.strip()
            if not part:
                continue
            
            base_cmd = part.split()[0]
            
            # Check if command after pipe is explicitly blocked
            if base_cmd in BLOCKED_AFTER_PIPE:
                return False, f"Command '{base_cmd}' cannot be used after a pipe for security reasons"
            
            # After first pipe, only allow safe commands
            if i > 0 and base_cmd not in SAFE_AFTER_PIPE:
                return False, f"Only safe read-only commands allowed after pipe. '{base_cmd}' not permitted"
        
        return True, None
    
    def validate_conditional(cmd):
        """Allow && and || if both sides are safe"""
        if "&&" not in cmd and "||" not in cmd:
            return True, None
        
        # Split by && or ||
        parts = re.split(r'&&|\|\|', cmd)
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            base_cmd = part.split()[0]
            
            # Check if it's a known safe command
            if base_cmd in SAFE_COMMANDS or base_cmd in IRIS_RESTRICTED:
                continue
            
            # Check if it's in controlled or dangerous (will be validated later)
            if base_cmd in CONTROLLED_COMMANDS or base_cmd in DANGEROUS_COMMANDS:
                continue
            
            # Unknown command in conditional
            return False, f"Command '{base_cmd}' in conditional expression not whitelisted"
        
        return True, None
    
    def validate_substitution(cmd):
        """Allow command substitution if inner command is safe"""
        # Extract commands within $() or ``
        substitutions = re.findall(r'\$\(([^)]+)\)|`([^`]+)`', cmd)
        
        if not substitutions:
            return True, None
        
        for subst in substitutions:
            inner_cmd = subst[0] or subst[1]
            inner_cmd = inner_cmd.strip()
            
            if not inner_cmd:
                continue
            
            base_cmd = inner_cmd.split()[0]
            
            # Only allow specific safe commands in substitution
            if base_cmd not in SAFE_IN_SUBSTITUTION:
                return False, f"Command '{base_cmd}' not allowed in command substitution. Only safe read-only commands permitted."
        
        return True, None
    
    def validate_redirection(cmd):
        """Allow output redirection to safe locations only"""
        # Check for here-documents (always blocked)
        if "<<" in cmd:
            return False, "Here-documents (<<) not allowed"
        
        # Input redirection is generally safe (just reading files)
        # Output redirection needs path validation
        if ">" in cmd or ">>" in cmd:
            # Extract target file path
            match = re.search(r'>>?\s+([^\s;|&]+)', cmd)
            if match:
                target = match.group(1).strip()
                
                # Check if target is in safe write paths
                if not any(target.startswith(path) for path in SAFE_WRITE_PATHS):
                    return False, f"Output redirection only allowed to: {', '.join(SAFE_WRITE_PATHS)}. Attempted: {target}"
        
        return True, None
    
    def validate_base_command(base_cmd, args):
        """Validate a base command and its arguments"""
        # Check if command is completely blocked
        if base_cmd in BLOCKED_COMMANDS:
            return False, f"Command '{base_cmd}' is not allowed for safety reasons"
        
        # Safe commands can run without restrictions
        if base_cmd in SAFE_COMMANDS:
            return True, None
        
        # Iris-restricted commands must operate within /iris-v3/
        if base_cmd in IRIS_RESTRICTED:
            path_args = [arg for arg in args if arg.startswith("/")]
            for path in path_args:
                if not path.startswith("/iris-v3/"):
                    return False, f"Command '{base_cmd}' can only access /iris-v3/ directory. Attempted: {path}"
            return True, None
        
        # Dangerous commands need special validation
        if base_cmd in DANGEROUS_COMMANDS:
            rules = DANGEROUS_COMMANDS[base_cmd]
            
            # Check for blocked flags
            blocked_flags = rules.get("blocked_flags", [])
            for flag in blocked_flags:
                if flag in args:
                    return False, f"Flag '{flag}' not allowed with '{base_cmd}' for safety"
            
            # Check path restrictions
            allowed_paths = rules.get("paths_only", [])
            if allowed_paths:
                path_args = [arg for arg in args if arg.startswith("/")]
                for path in path_args:
                    if not any(path.startswith(allowed) for allowed in allowed_paths):
                        return False, f"Command '{base_cmd}' can only operate on: {', '.join(allowed_paths)}. Attempted: {path}"
            
            return True, None
        
        # Controlled commands have specific rules
        if base_cmd in CONTROLLED_COMMANDS:
            rules = CONTROLLED_COMMANDS[base_cmd]
            
            # Enforce argument limits
            max_args = rules.get("max_args")
            if max_args and len(args) > max_args:
                return False, f"Command '{base_cmd}' accepts maximum {max_args} arguments"
            
            # Require arguments
            if rules.get("require_args") and not args:
                return False, f"Command '{base_cmd}' requires arguments"
            
            # Check blocked flags
            blocked_flags = rules.get("blocked_flags", [])
            for flag in blocked_flags:
                if flag in args:
                    return False, f"Flag '{flag}' not allowed with '{base_cmd}'"
            
            # Check path restrictions
            allowed_paths = rules.get("paths_only", [])
            if allowed_paths:
                path_args = [arg for arg in args if arg.startswith("/")]
                for path in path_args:
                    if not any(path.startswith(allowed) for allowed in allowed_paths):
                        return False, f"Command '{base_cmd}' can only operate on: {', '.join(allowed_paths)}"
            
            return True, None
        
        # Command not in any whitelist
        return False, f"Command '{base_cmd}' is not in the allowed whitelist"
    
    # ========== MAIN VALIDATION ==========
    
    # Check for empty command
    if not command or not command.strip():
        return {"success": False, "error": "Empty command"}
    
    # Check for always-blocked patterns
    for pattern in ALWAYS_BLOCKED:
        if pattern in command:
            return {
                "success": False,
                "error": f"Pattern '{pattern}' is not allowed (command chaining/variable expansion blocked)"
            }
    
    # Validate special shell features
    validators = {
        "|": validate_pipes,
        "&&": validate_conditional,
        "||": validate_conditional,
        "$(": validate_substitution,
        "`": validate_substitution,
        ">": validate_redirection,
        ">>": validate_redirection,
    }
    
    for pattern, validator in validators.items():
        if pattern in command:
            is_valid, error = validator(command)
            if not is_valid:
                return {"success": False, "error": error}
    
    # Parse and validate base command(s)
    # Split by pipes, conditionals to get individual commands
    command_parts = re.split(r'[|]|&&|\|\|', command)
    
    for part in command_parts:
        # Remove redirections for parsing
        part = re.sub(r'>>?[^|&;]+', '', part)
        part = part.strip()
        
        if not part:
            continue
        
        # Remove command substitutions for parsing (already validated)
        part = re.sub(r'\$\([^)]+\)|`[^`]+`', '', part)
        part = part.strip()
        
        if not part:
            continue
        
        # Parse command and arguments
        tokens = part.split()
        if not tokens:
            continue
        
        base_cmd = tokens[0]
        args = tokens[1:] if len(tokens) > 1 else []
        
        # Validate this command
        is_valid, error = validate_base_command(base_cmd, args)
        if not is_valid:
            return {"success": False, "error": error}
    
    # ========== EXECUTION ==========
    try:
        # Execute with timeout for safety
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,  # 30 second timeout
            executable="/bin/bash",
            cwd="/iris-v3"  # Default to Iris's home directory
        )
        
        return {
            "success": True,
            "output": result.stdout.strip(),
            "error": result.stderr.strip() if result.stderr else None
        }
    
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Command timed out after 30 seconds"
        }
    
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "error": f"Command failed with exit code {e.returncode}: {e.stderr.strip() if e.stderr else 'Unknown error'}"
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }


@server.register_tool
def database_query(query: str) -> dict:
    """
    Execute SQL queries on Iris's database with automatic token safety limits.

    IMPORTANT: This tool estimates result size BEFORE executing queries.
    If a query would return more than 3000 tokens, it returns error "QUERY_TOO_LARGE"
    with the estimated token count. Refine your query with LIMIT, fewer columns,
    or more specific WHERE conditions.

    Successful queries include 'estimated_tokens' so you can see how close you are
    to the limit.

    BEST PRACTICE: Always use *_readable views (episodic_memories_readable,
    chat_history_readable) instead of base tables to avoid embedding columns.

    Args:
        query: SQL query statement (SELECT, SHOW, DESCRIBE, EXPLAIN, UPDATE, INSERT, ALTER allowed)

    Returns:
        dict with:
          - success: bool
          - results: list of row dicts (if successful)
          - estimated_tokens: int (if successful)
          - error: str (if failed)
          - message: str (if QUERY_TOO_LARGE, explains how to fix)
    """
    import psycopg2
    from database.persistence import get_db_connection
    
    # Whitelist of allowed operations
    ALLOWED_PREFIXES = ["SELECT", "SHOW", "DESCRIBE", "EXPLAIN", "UPDATE", "INSERT", "ALTER", "\\d", "\\dt"]
    
    # Dangerous keywords that indicate modification
    BLOCKED_KEYWORDS = [
        "DROP", "DELETE", "TRUNCATE",
        "CREATE", "GRANT", "REVOKE", "EXECUTE", "CALL"
    ]
    
    query_upper = query.strip().upper()
    
    # Check if query starts with allowed prefix
    if not any(query_upper.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        return {
            "success": False,
            "error": "Only SELECT, SHOW, DESCRIBE, and EXPLAIN queries allowed"
        }
    
    # Check for blocked keywords as standalone words (not in column names like "created_at")
    import re
    for keyword in BLOCKED_KEYWORDS:
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, query_upper):
            return {
                "success": False,
                "error": f"Modification operations not allowed. Blocked keyword: {keyword}"
            }

    # ---------------------------
    # STEP 1: TOKEN ESTIMATION
    # (ISOLATED TRANSACTION)
    # ---------------------------
    estimated_tokens = None

    token_check_query = f"""
    SELECT SUM((LENGTH(CONCAT(t.*)))/4)
    FROM ({query.rstrip(';')}) as t
    """

    try:
        est_conn = get_db_connection()
        est_cursor = est_conn.cursor()

        est_cursor.execute(token_check_query)
        result = est_cursor.fetchone()
        estimated_tokens = int(result[0]) if result and result[0] else 0

        import sys
        sys.path.insert(0, str(PROJECT_ROOT))
        from app import config
        max_tokens = getattr(config, 'MAX_SQL_RESULT_TOKENS', 8000)
        max_tokens = 8000

        if estimated_tokens > max_tokens:
            est_cursor.close()
            est_conn.close()
            return {
                "success": False,
                "error": "QUERY_TOO_LARGE",
                "message": (
                    f"Query would return approximately {estimated_tokens} tokens, "
                    f"exceeding the {max_tokens} token limit. Please refine your query "
                    f"with LIMIT, fewer columns, or more specific WHERE conditions."
                ),
                "estimated_tokens": estimated_tokens,
                "threshold": max_tokens
            }

        est_cursor.close()
        est_conn.close()

    except psycopg2.Error as token_check_error:
        # Token estimation failure is logged but does NOT block the query
        print(
            "[system_server.py][database_query] "
            f"Token estimation failed (continuing): {token_check_error.pgerror}"
        )
        try:
            est_conn.rollback()
            est_conn.close()
        except Exception:
            pass

    # ---------------------------
    # STEP 2: ACTUAL QUERY
    # (CLEAN TRANSACTION)
    # ---------------------------
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(query)

        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()

        results = []
        for row in rows:
            results.append(dict(zip(columns, row)))

        cursor.close()
        conn.close()

        return {
            "success": True,
            "columns": columns,
            "results": results,
            "row_count": len(results),
            "estimated_tokens": estimated_tokens
        }

    except psycopg2.Error as e:
        diag = e.diag
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass

        return {
            "success": False,
            "error": e.pgerror,
            "sqlstate": e.pgcode,
            "severity": diag.severity,
            "detail": diag.message_detail,
            "hint": diag.message_hint,
            "position": diag.statement_position,
            "constraint": diag.constraint_name,
            "table": diag.table_name,
            "column": diag.column_name,
        }

    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass

        return {
            "success": False,
            "error": f"Query failed: {str(e)}"
        }


# def database_query(query: str) -> dict:
#     """
#     Execute SQL queries on Iris's database with automatic token safety limits.

#     IMPORTANT: This tool estimates result size BEFORE executing queries.
#     If a query would return more than 3000 tokens, it returns error "QUERY_TOO_LARGE"
#     with the estimated token count. Refine your query with LIMIT, fewer columns,
#     or more specific WHERE conditions.

#     Successful queries include 'estimated_tokens' so you can see how close you are
#     to the limit.

#     BEST PRACTICE: Always use *_readable views (episodic_memories_readable,
#     chat_history_readable) instead of base tables to avoid embedding columns.

#     Args:
#         query: SQL query statement (SELECT, SHOW, DESCRIBE, EXPLAIN, UPDATE, INSERT, ALTER allowed)

#     Returns:
#         dict with:
#           - success: bool
#           - results: list of row dicts (if successful)
#           - estimated_tokens: int (if successful)
#           - error: str (if failed)
#           - message: str (if QUERY_TOO_LARGE, explains how to fix)
#     """
#     import psycopg2
#     from database.persistence import get_db_connection
    
#     # Whitelist of allowed operations
#     ALLOWED_PREFIXES = ["SELECT", "SHOW", "DESCRIBE", "EXPLAIN", "UPDATE", "INSERT", "ALTER", "\\d", "\\dt"]
    
#     # Dangerous keywords that indicate modification
#     BLOCKED_KEYWORDS = [
#         "DROP", "DELETE", "TRUNCATE",
#         "CREATE", "GRANT", "REVOKE", "EXECUTE", "CALL"
#     ]
    
#     query_upper = query.strip().upper()
    
#     # Check if query starts with allowed prefix
#     if not any(query_upper.startswith(prefix) for prefix in ALLOWED_PREFIXES):
#         return {
#             "success": False,
#             "error": "Only SELECT, SHOW, DESCRIBE, and EXPLAIN queries allowed"
#         }
    
#     # Check for blocked keywords as standalone words (not in column names like "created_at")
#     # Use word boundaries to avoid false positives
#     import re
#     for keyword in BLOCKED_KEYWORDS:
#         # Match keyword as a whole word, not as substring
#         pattern = r'\b' + re.escape(keyword) + r'\b'
#         if re.search(pattern, query_upper):
#             return {
#                 "success": False,
#                 "error": f"Modification operations not allowed. Blocked keyword: {keyword}"
#             }
    
#     try:
#         conn = get_db_connection()
#         cursor = conn.cursor()

#         # Step 1: Estimate token count BEFORE executing actual query
#         # Using Victor's proven CONCAT approach
#         token_check_query = f"""
#         SELECT SUM((LENGTH(CONCAT(t.*)))/4)
#         FROM ({query.rstrip(';')}) as t
#         """

#         try:
#             cursor.execute(token_check_query)
#             result = cursor.fetchone()
#             estimated_tokens = int(result[0]) if result and result[0] else 0

#             # Step 2: Check against threshold
#             import sys
#             sys.path.insert(0, str(PROJECT_ROOT))
#             from app import config
#             max_tokens = getattr(config, 'MAX_SQL_RESULT_TOKENS', 8000)
#             max_tokens = 8000
            
#             if estimated_tokens > max_tokens:
#                 cursor.close()
#                 conn.close()
#                 return {
#                     "success": False,
#                     "error": "QUERY_TOO_LARGE",
#                     "message": f"Query would return approximately {estimated_tokens} tokens, exceeding the {max_tokens} token limit. Please refine your query with LIMIT, fewer columns, or more specific WHERE conditions.",
#                     "estimated_tokens": estimated_tokens,
#                     "threshold": max_tokens
#                 }

#         except Exception as token_check_error:
#             # If token estimation fails, log but continue (don't block the query)
#             # This ensures backward compatibility if CONCAT doesn't work on some queries
#             print(f"[system_server.py][database_query] Token estimation failed (continuing): {token_check_error}")

#         # Step 3: Execute actual query if token check passed
#         cursor.execute(query)
        
#         # Get column names
#         columns = [desc[0] for desc in cursor.description] if cursor.description else []
        
#         # Fetch results
#         rows = cursor.fetchall()
        
#         # Format results as list of dicts
#         results = []
#         for row in rows:
#             results.append(dict(zip(columns, row)))
        
#         cursor.close()
#         conn.close()

#         return {
#             "success": True,
#             "columns": columns,
#             "results": results,
#             "row_count": len(results),
#             "estimated_tokens": estimated_tokens if 'estimated_tokens' in locals() else None
#         }
    
#     except psycopg2.Error as e:
#         conn.rollback()
#         diag = e.diag
#         return({
#             "success": False,
#             "message": f"psycopg2 error: {e.pgerror}",
#             "sqlstate": e.pgcode,
#             "severity": diag.severity,
#             "detail": diag.message_detail,
#             "hint": diag.message_hint,
#             "position": diag.statement_position,
#             "constraint": diag.constraint_name,
#             "table": diag.table_name,
#             "column": diag.column_name,
#         })
        
    
#     except Exception as e:
#         return {
#             "success": False,
#             "error": f"Query failed: {str(e)}"
#         }

# ============================================================================
# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    print("="*60)
    print("IRIS INFO SERVER")
    print("="*60)
    print(f"Tools available: system_status")
    print(f"Starting server...")
    print("="*60)
    print("running shell")
   #result = linux_shell("ls /iris-v3/")
   #print(result)
    server.run()

# # Example usage
# if __name__ == "__main__":
#     # Get comprehensive system statistics
#     health_stats = get_system_health_statistics()
    
#     # Print formatted summary
#     # print(format_system_health_summary(health_stats))
#     print(health_stats)
#     # Or get raw JSON data for programmatic use
#     # print(json.dumps(health_stats, indent=2))