#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Viper UI Display Module
负责3D可视化显示
"""

import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from collections import deque
import queue
import time


class Viper3DVisualizer:
    """3D Visualization Class"""
    
    def __init__(self, data_queue):
        self.data_queue = data_queue
        self.fig = None
        self.ax = None
        self.info_ax = None  # Text info display axis
        self.sensor_points = {}  # Store current points for each sensor
        self.sensor_trails = {}  # Store trajectories for each sensor
        self.max_trail_length = 100  # Maximum trail length
        self.running = True
        self.coord_range = 100  # Fixed coordinate range
        self.update_interval = 0.1  # Update every 0.1 seconds (10 FPS)
        self.last_update_time = 0
        self.latest_data = None  # Store latest sensor data
        
    def init_plot(self):
        """Initialize 3D plot"""
        plt.ion()  # Enable interactive mode
        self.fig = plt.figure(figsize=(14, 10))
        
        # Create subplots: 3D plot on top, text info at bottom
        gs = self.fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.3)
        
        # 3D plot
        self.ax = self.fig.add_subplot(gs[0], projection='3d')
        
        # Text info area
        self.info_ax = self.fig.add_subplot(gs[1])
        self.info_ax.axis('off')
        self.info_text = None
        
        # Set axis labels
        self.ax.set_xlabel('X (mm)')
        self.ax.set_ylabel('Y (mm)')
        self.ax.set_zlabel('Z (mm)')
        self.ax.set_title('Viper Sensor Real-time Position Tracking')
        
        # Set fixed coordinate range
        self.ax.set_xlim([-self.coord_range, self.coord_range])
        self.ax.set_ylim([-self.coord_range, self.coord_range])
        self.ax.set_zlim([-self.coord_range, self.coord_range])
        
        # Add grid
        self.ax.grid(True)
        
        # Set view angle
        self.ax.view_init(elev=20, azim=45)
        
        plt.tight_layout()
    
    def euler_to_rotation_matrix(self, euler):
        """Convert Euler angles (azimuth, elevation, roll) to rotation matrix"""
        az, el, roll = euler[0], euler[1], euler[2]
        
        # Convert to radians
        az = np.radians(az)
        el = np.radians(el)
        roll = np.radians(roll)
        
        # Rotation matrices
        Rz = np.array([[np.cos(az), -np.sin(az), 0],
                       [np.sin(az), np.cos(az), 0],
                       [0, 0, 1]])
        
        Ry = np.array([[np.cos(el), 0, np.sin(el)],
                       [0, 1, 0],
                       [-np.sin(el), 0, np.cos(el)]])
        
        Rx = np.array([[1, 0, 0],
                       [0, np.cos(roll), -np.sin(roll)],
                       [0, np.sin(roll), np.cos(roll)]])
        
        # Combined rotation: R = Rz * Ry * Rx
        R = Rz @ Ry @ Rx
        return R
    
    def draw_rotated_box(self, pos, ori, size=5, color='blue', alpha=0.7):
        """Draw a rotated box at position with orientation"""
        # Box vertices (centered at origin, size x size x size*2)
        box_vertices = np.array([
            [-size, -size, -size],
            [size, -size, -size],
            [size, size, -size],
            [-size, size, -size],
            [-size, -size, size],
            [size, -size, size],
            [size, size, size],
            [-size, size, size]
        ])
        
        # Get rotation matrix from Euler angles
        R = self.euler_to_rotation_matrix(ori)
        
        # Rotate box vertices
        rotated_vertices = (R @ box_vertices.T).T
        
        # Translate to position
        rotated_vertices += pos
        
        # Define box faces (6 faces, each with 4 vertices)
        faces = [
            [0, 1, 2, 3],  # bottom
            [4, 5, 6, 7],  # top
            [0, 1, 5, 4],  # front
            [2, 3, 7, 6],  # back
            [0, 3, 7, 4],  # left
            [1, 2, 6, 5]   # right
        ]
        
        # Draw each face using Poly3DCollection
        face_collection = []
        for face in faces:
            face_vertices = rotated_vertices[face]
            face_collection.append(face_vertices)
        
        # Create Poly3DCollection for all faces
        poly3d = Poly3DCollection(face_collection, 
                                  facecolors=color, 
                                  edgecolors='black', 
                                  linewidths=0.5, 
                                  alpha=alpha)
        self.ax.add_collection3d(poly3d)
        
    def update_plot(self, sensors_data):
        """Update 3D plot"""
        if self.ax is None:
            return
        
        # Clear previous plot
        self.ax.clear()
        
        # Reset axes
        self.ax.set_xlabel('X (mm)')
        self.ax.set_ylabel('Y (mm)')
        self.ax.set_zlabel('Z (mm)')
        self.ax.set_title('Viper Sensor Real-time Position Tracking')
        self.ax.grid(True)
        
        # Set fixed coordinate range
        self.ax.set_xlim([-self.coord_range, self.coord_range])
        self.ax.set_ylim([-self.coord_range, self.coord_range])
        self.ax.set_zlim([-self.coord_range, self.coord_range])
        
        # Draw coordinate origin
        origin = np.array([0, 0, 0])
        self.ax.scatter(origin[0], origin[1], origin[2], 
                       c='red', s=50, marker='o', label='Origin')
        
        # Colors for sensors
        colors = plt.cm.tab20(np.linspace(0, 1, 16))
        
        for sensor in sensors_data:
            sensor_num = sensor['num']
            pos = np.array(sensor['pos'])
            ori = sensor['ori']
            
            # Initialize trajectory
            if sensor_num not in self.sensor_trails:
                self.sensor_trails[sensor_num] = deque(maxlen=self.max_trail_length)
            
            # Add current position to trajectory
            self.sensor_trails[sensor_num].append(pos)
            
            # Get color for this sensor
            color = colors[(sensor_num - 1) % len(colors)]
            
            # Draw trajectory
            if len(self.sensor_trails[sensor_num]) > 1:
                trail = np.array(self.sensor_trails[sensor_num])
                self.ax.plot(trail[:, 0], trail[:, 1], trail[:, 2], 
                           color=color, alpha=0.3, linewidth=1)
            
            # Draw line from origin to current position
            self.ax.plot3D([origin[0], pos[0]], 
                          [origin[1], pos[1]], 
                          [origin[2], pos[2]], 
                          color=color, linewidth=2, alpha=0.5)
            
            # Draw rotated box to show orientation
            box_size = 3
            # Convert color from RGBA to RGB tuple for Poly3DCollection
            color_rgb = tuple(color[:3]) if len(color) > 3 else color
            self.draw_rotated_box(pos, ori, size=box_size, 
                                 color=color_rgb, alpha=0.7)
            
            # Draw current position point
            self.ax.scatter(pos[0], pos[1], pos[2], 
                          c=[color], s=100, marker='o', 
                          edgecolors='black', linewidths=1)
            
            # Add text label
            self.ax.text(pos[0], pos[1], pos[2], f' S{sensor_num}', fontsize=8)
        
        # Add legend (only show first few sensors to avoid clutter)
        if len(sensors_data) <= 8:
            self.ax.legend(loc='upper left', fontsize=8)
        
        # Update text info display
        self.update_info_text(sensors_data)
        
        # Refresh plot
        plt.draw()
        plt.pause(0.01)
    
    def update_info_text(self, sensors_data):
        """Update text information display with real-time coordinates and rotation"""
        if self.info_ax is None:
            return
        
        # Clear previous text
        self.info_ax.clear()
        self.info_ax.axis('off')
        
        # Create info text with header
        info_lines = ["Real-time Sensor Data:", "=" * 100]
        info_lines.append(f"{'Sensor':<8} {'X (mm)':>10} {'Y (mm)':>10} {'Z (mm)':>10}  |  {'Azimuth(°)':>12} {'Elevation(°)':>13} {'Roll(°)':>10}")
        info_lines.append("-" * 100)
        
        for sensor in sensors_data:
            sensor_num = sensor['num']
            pos = sensor['pos']
            ori = sensor['ori']
            
            # Format each value
            info_line = (f"Sensor {sensor_num:<2} "
                        f"{pos[0]:>10.3f} {pos[1]:>10.3f} {pos[2]:>10.3f}  |  "
                        f"{ori[0]:>12.2f} {ori[1]:>13.2f} {ori[2]:>10.2f}")
            info_lines.append(info_line)
        
        # Display text
        info_text = "\n".join(info_lines)
        self.info_ax.text(0.02, 0.95, info_text, 
                         transform=self.info_ax.transAxes,
                         fontsize=9, 
                         family='monospace',
                         verticalalignment='top',
                         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    def run(self):
        """Run visualization loop"""
        self.init_plot()
        self.last_update_time = time.time()
        
        try:
            while self.running:
                # Check if window is closed
                if self.fig is None or not plt.fignum_exists(self.fig.number):
                    print("\nWindow closed, exiting...")
                    self.running = False
                    break
                
                current_time = time.time()
                time_since_last_update = current_time - self.last_update_time
                
                # Try to get latest data from queue (non-blocking, consume all available)
                # This ensures we always use the most recent data
                try:
                    while True:
                        data = self.data_queue.get_nowait()
                        self.latest_data = data  # Keep only the latest data
                except queue.Empty:
                    pass
                
                # Update plot only if enough time has passed (10 FPS = 0.1s interval)
                if time_since_last_update >= self.update_interval:
                    if self.latest_data is not None:
                        self.update_plot(self.latest_data['sensors'])
                        self.last_update_time = current_time
                    else:
                        # If no data yet, just pause briefly
                        plt.pause(0.01)
                else:
                    # Wait until it's time for next update
                    remaining_time = self.update_interval - time_since_last_update
                    if remaining_time > 0.001:  # Only sleep if significant time remains
                        plt.pause(min(remaining_time, 0.01))
                    
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"Visualization update error: {e}")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Cleanup resources"""
        self.running = False
        if self.fig is not None:
            plt.close(self.fig)

