# 本机只读主机识别 v1

edge-agent inspect-host 输出 enterprise-host-inspection/v1 JSON，不联网、不注册、不上传。Linux 固定读取 /etc/os-release、/sys/class/dmi/id/product_name、/proc/device-tree/model，单文件最多 16 KiB，只提取 OS ID/VERSION_ID 与限长产品型号，不读取主机名、序列号、机器 ID、用户目录或配置。shell 语法不执行，异常值不回显。

process_arch 是当前 Edge 二进制架构，kernel_machine 来自 uname；二者不能当作等价的物理 CPU 认证。系统元数据缺失、权限拒绝、异常和可读取分别标为 missing、permission_denied、unavailable、observed；未观测绝不显示为“不存在框架/没有资产”。

产品型号仅是本机固件/设备树报告，不能凭用户环境名或字符串“DGX Spark”认证硬件。输出 hardware_attested=false、business_permissions_granted=false、uploaded=false。不推断 GPU/OpenShell 安装或有效隔离。后续安装引导可消费此输出，本命令不自动选择组织或授予范围。

Linux setup-enterprise --interactive 已复用此观察，在确认范围前显示本地摘要及来源，
所有值以转义文本输出。仍不上传主机报告、不自动选组织、不改变采集计划；后台心跳
和控制面设备硬件信息尚未接入此报告，不能把本地摘要等同于企业端已盘点硬件。
