#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Viper Main Program
主程序，连接USB通讯模块和显示模块
"""

import sys
import queue
import threading
from viper_usb_comm import ViperUSBComm
from viper_ui_display import Viper3DVisualizer




def main():
    """Main function"""
    # Create data queue for passing data between USB communication and display
    data_queue = queue.Queue(maxsize=10)
    
    # Create Viper USB communication object
    viper = ViperUSBComm(data_queue=data_queue, trace_dir="trace")
    
    # Create 3D visualization object
    visualizer = Viper3DVisualizer(data_queue)
    
    try:
        # Connect USB device
        if not viper.connect():
            print("Failed to connect USB device")
            return 1
        
        # Start continuous mode
        if not viper.start_continuous():
            print("Failed to start continuous mode")
            viper.disconnect()
            return 1
        
        # Start reading thread
        read_thread = threading.Thread(target=viper.read_usb_data, daemon=True)
        read_thread.start()
        
        print("\nStarting USB data reading and 3D visualization (Close window or press Ctrl+C to exit)...\n")
        
        # Start 3D visualization (runs in main thread, as matplotlib needs main thread)
        try:
            visualizer.run()
        except KeyboardInterrupt:
            print("\n\nStopping...")
        finally:
            # Ensure cleanup happens
            visualizer.running = False
            viper.keep_reading = False
            viper.is_continuous = False
            
            # Wait for read thread to finish
            if read_thread.is_alive():
                read_thread.join(timeout=2)
            
            # Disconnect device (this will stop continuous mode and logging)
            viper.disconnect()
            print("Exited")
    
    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Ensure cleanup in all cases
        if 'visualizer' in locals():
            visualizer.running = False
        if 'viper' in locals():
            viper.keep_reading = False
            viper.is_continuous = False
            viper.disconnect()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

