#!/bin/bash
set -euo pipefail

REMOTE_USER="user"
REMOTE_IP="192.168.0.39"
REMOTE_FILE1="$HOME/core-cap"   # 远程文件绝对路径（$HOME替代~，避免解析问题）
REMOTE_FILE2="$HOME/core-gos"
SSH_PORT=22                  # 39机器SSH端口，非22请修改

# ==================== 函数定义 ====================
# 检查SSH连接是否可用
check_ssh_connection() {
    echo "🔍 检查与 ${REMOTE_IP}:${SSH_PORT} 的SSH连接..."
    if ! ssh -p ${SSH_PORT} -q ${REMOTE_USER}@${REMOTE_IP} "exit"; then
        echo "❌ 错误：无法连接到 ${REMOTE_IP}，请检查网络/SSH配置！"
        exit 1
    fi
    echo "✅ SSH连接正常"
}

# 远程检测并杀死指定进程
kill_existing_process() {
    local target_file=$1
    local process_name=$(basename "${target_file}")  # 提取文件名（如ccore、gos）

    echo -e "\n🔍 检测远程机器是否有 ${process_name} 进程运行..."
    # 远程执行：检测进程（pgrep -f 匹配完整命令行，排除grep自身）
    local pid_list
    pid_list=$(ssh -p ${SSH_PORT} ${REMOTE_USER}@${REMOTE_IP} "pgrep -f '${target_file}' || true")

    if [ -n "${pid_list}" ]; then
        echo "⚠️  发现 ${process_name} 进程（PID: ${pid_list}），强制杀死..."
        # 强制杀死进程，忽略kill失败（如进程已退出）
        ssh -p ${SSH_PORT} ${REMOTE_USER}@${REMOTE_IP} "kill -9 ${pid_list} || true"
        # 验证进程是否被杀死
        local remaining_pid
        remaining_pid=$(ssh -p ${SSH_PORT} ${REMOTE_USER}@${REMOTE_IP} "pgrep -f '${target_file}' || true")
        if [ -z "${remaining_pid}" ]; then
            echo "✅ ${process_name} 旧进程已清理"
        else
            echo "❌ 错误：无法杀死 ${process_name} 进程（PID: ${remaining_pid}），请手动检查！"
            exit 1
        fi
    else
        echo "✅ 未发现 ${process_name} 旧进程"
    fi
}

# 远程执行目标文件
execute_remote_files() {
    echo -e "\n🔧 为远程文件赋予可执行权限..."
    ssh -p ${SSH_PORT} ${REMOTE_USER}@${REMOTE_IP} "chmod +x ${REMOTE_FILE1} ${REMOTE_FILE2} || true"

    echo -e "\n🚀 开始执行 ${REMOTE_FILE1} 和 ${REMOTE_FILE2}..."
    # 依次执行，前一个成功后执行后一个；若需并行执行，将 && 换成 &
    ssh -p ${SSH_PORT} ${REMOTE_USER}@${REMOTE_IP} "${REMOTE_FILE1} && ${REMOTE_FILE2}"

    # 检查执行结果
    if [ $? -eq 0 ]; then
        echo -e "\n🎉 远程执行成功！"
    else
        echo -e "\n❌ 远程执行失败！"
        exit 1
    fi
}

# ==================== 主流程 ====================
main() {
    check_ssh_connection
    kill_existing_process "${REMOTE_FILE1}"  # 清理ccore旧进程
    kill_existing_process "${REMOTE_FILE2}"  # 清理gos旧进程
    execute_remote_files
}

# 启动主流程
main