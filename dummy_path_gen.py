import numpy as np
import matplotlib.pyplot as plt

def make_path(start, target, num_points):

    t = np.linspace(0, 1, num_points)

    # 设计减速曲线：使用指数函数使速度逐渐减慢至0
    # 函数形式确保t=0时在起点，t=1时在终点，且导数逐渐减小
    decay = 1 - np.exp(-5 * t)  # 衰减曲线，控制速度变化

    # 计算每个维度的坐标
    x = start[0] + (target[0] - start[0]) * decay
    y = start[1] + (target[1]- start[1]) * decay
    z = start[2] + (target[2] - start[2]) * decay

    # 添加微小的随机扰动，模拟人手操作的轻微抖动
    np.random.seed(42)  # 固定随机种子，保证结果可复现
    noise = 0.008 * np.exp(-4 * t)  # 扰动随时间减小，最后几乎稳定
    x += noise * np.random.randn(num_points)
    y += noise * np.random.randn(num_points)
    z += noise * np.random.randn(num_points)

    # 确保最后一点精确到达目标位置
    x[-1], y[-1], z[-1] = target[0], target[1], target[2]

    # 组合坐标
    coordinates = np.column_stack((x, y, z))
    return coordinates

p1 = [0.3, 0.5, 0.1]
coordinates1 = make_path([0.7, 0.8, 0.5],p1, 200)
coordinates2 = make_path(p1,[0.4, 0.2, 0.1], 100)
coordinates = np.concatenate((coordinates1,coordinates2), axis=0)

# 保存到文件
with open('path.txt', 'w') as f:
    for coord in coordinates:
        f.write(f"{coord[0]:.6f}, {coord[1]:.6f}, {coord[2]:.6f}\n")

# # 可视化路径（可选）
# fig = plt.figure(figsize=(10, 8))
# ax = fig.add_subplot(111, projection='3d')
# ax.plot(x, y, z, 'b-', linewidth=1.5)
# ax.scatter(target_x, target_y, target_z, c='r', s=100, label='目标位置')
# ax.scatter(start_x, start_y, start_z, c='g', s=100, label='起始位置')
# ax.set_xlabel('X')
# ax.set_ylabel('Y')
# ax.set_zlabel('Z')
# ax.set_title('探头操作路径模拟')
# ax.legend()
# plt.show()

print(f"已生成坐标数据，保存至path.txt")