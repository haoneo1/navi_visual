"""Efficient image data package storage module"""
import struct
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("Warning: numpy not available, data package functionality will be limited")

import cv2
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
import json
import os


class DataPackage:
    """Efficient image data package storage class

    Single file format (binary):
    - Header (80 bytes):
      - magic: 4 bytes ('uPKG')
      - version: 4 bytes (uint32)
      - image_type: 16 bytes (str, padded)
      - width: 4 bytes (uint32) - image width
      - height: 4 bytes (uint32) - image height
      - frame_count: 4 bytes (uint32)
      - header_size: 4 bytes (uint32)
      - index_offset: 8 bytes (uint64) - index section start position
      - image_offset: 8 bytes (uint64) - image section start position
      - trace_offset: 8 bytes (uint64) - trace section start position
      - reserved: 16 bytes
    - Index entries (32 bytes each):
      - timestamp: 8 bytes (uint64, microseconds)
      - image_offset: 8 bytes (uint64) - image data offset in image section
      - image_size: 4 bytes (uint32) - image data size
      - trace_offset: 8 bytes (uint64) - trace offset in metadata section
      - trace_size: 4 bytes (uint32) - trace data size
    - Image section: all image data stored continuously
    - Trace section: all trace stored continuously
    """

    def __init__(self, save_path: str, image_type='nv12', width: int = 1920, height: int = 1088, realtime: bool = False):
        if not HAS_NUMPY:
            raise ImportError("numpy is required for DataPackage functionality")
    
    MAGIC = b'uPKG'
    VERSION = 1
    HEADER_SIZE = 80
    INDEX_ENTRY_SIZE = 32
    STRUCT_INDEX_FORMAT = '<QQIQI'  # timestamp(8), img_offset(8), img_size(4), trace_offset(8), meta_size(4)
    FILE_EXTENSION = '.upkg'
    
    def __init__(self, save_path: str, image_type: str = 'nv12', width: int = 0, height: int = 0, realtime: bool = False):
        """Initialize data package
        
        Args:
            save_path: Save path
            image_type: Image type ('nv12', 'rgb', 'bgr', 'png', 'jpg', etc.)
            width: Image width (pixels)
            height: Image height (pixels)
            realtime: if True, write image/trace data to temp files immediately on add_frame()
        """
        self.save_path = Path(save_path)
        if not self.save_path.suffix:
            self.save_path = self.save_path.with_suffix('.upkg')
        self.image_type = image_type.lower()
        self.width = width
        self.height = height
        self.recording = False
        # In non-realtime mode we keep full frames in memory until save()
        self.frames: List[Tuple[float, np.ndarray, Dict[str, Any]]] = []
        # In realtime mode we write image/trace data to temp files and keep a small index in memory
        self.realtime = bool(realtime)
        self._realtime_index: List[Dict[str, Any]] = []
        self._images_temp_path: Optional[Path] = None
        self._traces_temp_path: Optional[Path] = None
        self._images_file = None
        self._traces_file = None
        self._images_write_offset = 0
        self._traces_write_offset = 0
        
        # 缓存
        self._index_cache: Optional[List[Dict]] = None
        self._trace_cache: Optional[List[Dict]] = None
        
        if width <= 0 or height <= 0:
            print(f"Warning: Image dimensions not set or invalid: width={width}, height={height}")
        # Initialize realtime temp files if requested
        if self.realtime:
            self._init_realtime_tempfiles()
    
    def start_recording(self):
        """Start recording data package"""
        if self.recording:
            print("Already recording")
            return
        
        self.recording = True
        self.frames = []
        print(f"Start recording data package: {self.save_path}, image type: {self.image_type}")
    
    def add_frame(self, time: float, image: np.ndarray, trace: [] = []):
        """Add a frame of data
        
        Args:
            time: Timestamp
            img: Image data (numpy array)
            data: Structured data (dict, optional)
        """
        if not self.recording:
            raise RuntimeError("Recording not started, please call start_recording() first")
        
        if trace is None:
            trace = []
        
        # Validate image type
        if self.image_type == 'nv12':
            if len(image.shape) != 1:
                raise ValueError(f"NV12 format requires 1D array, got shape: {image.shape}")
        elif self.image_type in ['rgb', 'bgr']:
            if len(image.shape) != 3:
                raise ValueError(f"{self.image_type.upper()} format requires 3D array (H,W,C), got shape: {image.shape}")
        # If realtime mode, write image/trace to temp files immediately and keep a small index
        if self.realtime:
            # encode image and trace
            image_bytes = self._encode_image(image)
            image_size = len(image_bytes)

            trace_json = json.dumps(trace, ensure_ascii=False)
            trace_bytes = trace_json.encode('utf-8')
            trace_size = len(trace_bytes)

            # record current offsets (relative to image/trace sections)
            image_rel_offset = self._images_write_offset
            trace_rel_offset = self._traces_write_offset

            # write image (length prefix + bytes)
            self._images_file.write(struct.pack('<I', image_size))
            self._images_file.write(image_bytes)
            self._images_file.flush()
            os.fsync(self._images_file.fileno())
            self._images_write_offset += 4 + image_size

            # write trace (length prefix + bytes)
            self._traces_file.write(struct.pack('<I', trace_size))
            self._traces_file.write(trace_bytes)
            self._traces_file.flush()
            os.fsync(self._traces_file.fileno())
            self._traces_write_offset += 4 + trace_size

            # append minimal index
            self._realtime_index.append({
                'timestamp': int(time * 1e6),
                'image_rel_offset': image_rel_offset,
                'image_size': image_size,
                'trace_rel_offset': trace_rel_offset,
                'trace_size': trace_size
            })

            print(f"Realtime: wrote frame {len(self._realtime_index)}: time={time:.3f}, img_bytes={image_size}, trace_bytes={trace_size}")
        else:
            # non-realtime: keep full frames in memory
            self.frames.append((time, image.copy(), trace.copy()))
            print(f"Added frame {len(self.frames)}: time={time:.3f}, img_shape={image.shape}")
    
    def save(self):
        """Save data package to disk"""
        if not self.recording:
            raise RuntimeError("Recording not started, please call start_recording() first")
        # determine frame count depending on mode
        frame_count = len(self._realtime_index) if self.realtime else len(self.frames)
        if frame_count == 0:
            print("No data to save")
            return
        
        print(f"Start saving data package: {frame_count} frames")
        
        # Create directory
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save to single file
        if self.realtime:
            # finalize realtime temp files into single package
            self._finalize_realtime()
        else:
            self._write_file()
        
        # Reset state
        self.recording = False
        self.frames = []
        print(f"Data package saved: {self.save_path}")
    
    def encode_header(self,
        frame_count: int, index_offset: int, image_offset: int, trace_offset: int
        ) -> bytes:

        header = struct.pack(
                '<4sI16sIIIIQQQ16s',    # 格式字符串
                self.MAGIC,         # 4 bytes
                self.VERSION,       # 4 bytes
                self.image_type.encode('utf-8').ljust(16, b'\0'),   # 16 bytes
                self.width,         # 4 bytes: 宽度
                self.height,        # 4 bytes: 高度    
                frame_count,        # 4 bytes: 帧数
                self.HEADER_SIZE,   # 4 bytes: 头部大小
                index_offset,       # 8 bytes: 索引区偏移
                image_offset,       # 8 bytes: 数据区偏移
                trace_offset,       # 8 bytes: 元数据区偏移
                b'\0' * 16          # 16 bytes: 保留
            )
        return header

    @classmethod
    def decode_header(cls, header: bytes) -> Tuple[bytes, int, str, int, int, int, int, int, int, int]:
        """Decode header bytes
        
        Args:
            header: Header bytes
            
        Returns:
            Tuple of (magic, version, image_type, width, height, frame_count, header_size, index_offset, image_offset, trace_offset)
        """
        if len(header) < cls.HEADER_SIZE:
            raise ValueError(f"Header too small: {len(header)} bytes, need {cls.HEADER_SIZE} bytes")
        
        magic, version, image_type_bytes, width, height, frame_count, header_size, index_offset, image_offset, trace_offset, _ = struct.unpack('<4sI16sIIIIQQQ16s', header)
        
        if magic != cls.MAGIC:
            raise ValueError(f"Invalid file format: magic={magic}")
        
        if header_size != cls.HEADER_SIZE:
            raise ValueError(f"Header size mismatch: {header_size} != {cls.HEADER_SIZE}")
        
        image_type = image_type_bytes.rstrip(b'\0').decode('utf-8')
        return magic, version, image_type, width, height, frame_count, header_size, index_offset, image_offset, trace_offset

    def _init_realtime_tempfiles(self):
        """Initialize temp files used for realtime writing of images and traces."""
        base = self.save_path.stem
        tmpdir = self.save_path.parent / f".{base}_parts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        self._images_temp_path = tmpdir / f"{base}.images.bin"
        self._traces_temp_path = tmpdir / f"{base}.traces.bin"
        # open in append binary mode
        self._images_file = open(self._images_temp_path, 'ab')
        self._traces_file = open(self._traces_temp_path, 'ab')
        # get current sizes
        try:
            self._images_write_offset = self._images_temp_path.stat().st_size
        except Exception:
            self._images_write_offset = 0
        try:
            self._traces_write_offset = self._traces_temp_path.stat().st_size
        except Exception:
            self._traces_write_offset = 0

    def _finalize_realtime(self):
        """Assemble final single-file package from realtime temp parts and in-memory index."""
        if not self._realtime_index:
            raise RuntimeError("No realtime frames to finalize")

        # ensure temp files are flushed and closed
        if self._images_file:
            self._images_file.flush()
            os.fsync(self._images_file.fileno())
            self._images_file.close()
            self._images_file = None
        if self._traces_file:
            self._traces_file.flush()
            os.fsync(self._traces_file.fileno())
            self._traces_file.close()
            self._traces_file = None

        frame_count = len(self._realtime_index)
        index_size = frame_count * self.INDEX_ENTRY_SIZE

        # compute image and trace section sizes from recorded index
        image_section_size = sum([(4 + e['image_size']) for e in self._realtime_index])
        trace_section_size = sum([(4 + e['trace_size']) for e in self._realtime_index])

        index_offset = self.HEADER_SIZE
        image_offset = index_offset + index_size
        trace_offset = image_offset + image_section_size

        # write final package
        with open(self.save_path, 'wb') as out_f:
            # header
            header = self.encode_header(frame_count, index_offset, image_offset, trace_offset)
            out_f.write(header)

            # write index entries (use relative offsets within image/trace sections)
            current_image_rel = 0
            current_trace_rel = 0
            for e in self._realtime_index:
                timestamp = int(e['timestamp'])
                image_size = int(e['image_size'])
                trace_size = int(e['trace_size'])
                # pack: timestamp, image_rel_offset, image_size, trace_rel_offset, trace_size
                index_entry = struct.pack(self.STRUCT_INDEX_FORMAT,
                                          timestamp,
                                          current_image_rel,
                                          image_size,
                                          current_trace_rel,
                                          trace_size)
                out_f.write(index_entry)
                current_image_rel += 4 + image_size
                current_trace_rel += 4 + trace_size

            # copy image bytes from temp file
            with open(self._images_temp_path, 'rb') as img_f:
                while True:
                    chunk = img_f.read(8192)
                    if not chunk:
                        break
                    out_f.write(chunk)

            # copy trace bytes from temp file
            with open(self._traces_temp_path, 'rb') as tr_f:
                while True:
                    chunk = tr_f.read(8192)
                    if not chunk:
                        break
                    out_f.write(chunk)

        # cleanup temp files and directory
        try:
            if self._images_temp_path and self._images_temp_path.exists():
                self._images_temp_path.unlink()
            if self._traces_temp_path and self._traces_temp_path.exists():
                self._traces_temp_path.unlink()
            tmpdir = self.save_path.parent / f".{self.save_path.stem}_parts"
            if tmpdir.exists():
                try:
                    tmpdir.rmdir()
                except OSError:
                    pass
        except Exception:
            pass

        # clear realtime index
        self._realtime_index = []


    def _write_file(self):
        """Write all data to a single file"""
        with open(self.save_path, 'wb') as f:
            # 1. 计算各区域大小
            frame_count = len(self.frames)
            
            # 计算索引区大小
            index_size = frame_count * self.INDEX_ENTRY_SIZE
            
            # 计算数据区和元数据区大小
            image_section_size = 0
            trace_section_size = 0
            image_sizes = []
            trace_sizes = []
            
            for time, image, trace in self.frames:
                # 计算图片数据大小
                image_bytes = self._encode_image(image)
                image_size = len(image_bytes)
                image_sizes.append(image_size)
                image_section_size += 4 + image_size  # 4字节大小 + 数据
                
                # 计算追踪数据大小
                trace_json = json.dumps(trace, ensure_ascii=False)
                trace_bytes = trace_json.encode('utf-8')
                trace_size = len(trace_bytes)
                trace_sizes.append(trace_size)
                trace_section_size += 4 + trace_size  # 4字节大小 + 数据
            
            # 2. 计算各区域偏移
            index_offset = self.HEADER_SIZE
            image_offset = index_offset + index_size
            trace_offset = image_offset + image_section_size
            
            print(f'W: idx_o={index_offset}, img_o={image_offset}, tra_o={trace_offset}')
            
            # 3. 写入头部
            header = self.encode_header(frame_count, index_offset, image_offset, trace_offset)
            f.write(header)

            print(f'W: header size:{len(header)}')

            print(f'width={self.width}, height={self.height}, frame_count={frame_count}')
            
            # 4. 写入索引区
            current_image_offset = 0
            current_trace_offset = 0
            
            for i, (time, image, trace) in enumerate(self.frames):
                image_size = image_sizes[i]
                trace_size = trace_sizes[i]
                
                # 写入索引条目
                index_entry = struct.pack(
                    self.STRUCT_INDEX_FORMAT,
                    int(time * 1e6),        # 时间戳（微秒）
                    current_image_offset,   # 图片数据偏移
                    image_size,             # 图片数据大小
                    current_trace_offset,   # 追踪数据偏移
                    trace_size              # 追踪数据大小
                )
                f.write(index_entry)

                print(f'W: index_sec: {len(index_entry)}, img_o={current_image_offset}, tra_o={current_trace_offset}')
                
                # 更新偏移
                current_image_offset += 4 + image_size  # 4字节大小 + 数据
                current_trace_offset += 4 + trace_size  # 4字节大小 + 数据
            
            # 5. 写入数据区
            for i, (time, image, trace) in enumerate(self.frames):
                image_bytes = self._encode_image(image)
                f.write(struct.pack('<I', len(image_bytes)))  # 4 bytes: 数据大小
                f.write(image_bytes)
                print(f'W: image_sec: {i}, {len(image_bytes)}')
            
            # 6. 写入元数据区
            for i, (time, image, trace) in enumerate(self.frames):
                trace_json = json.dumps(trace, ensure_ascii=False)
                trace_bytes = trace_json.encode('utf-8')
                f.write(struct.pack('<I', len(trace_bytes)))  # 4 bytes: 数据大小
                f.write(trace_bytes)
                print(f'W: trace_sec: {i}, {len(trace_bytes)}, {trace_bytes}')
    
    def _encode_image(self, img: np.ndarray) -> bytes:
        """Encode image data"""
        if self.image_type == 'nv12':
            return img.tobytes()
        elif self.image_type in ['rgb', 'bgr']:
            return img.tobytes()
        elif self.image_type in ['png', 'jpg', 'jpeg']:
            if self.image_type in ['jpg', 'jpeg']:
                encode_param = [cv2.IMWRITE_JPEG_QUALITY, 95]
                ext = '.jpg'
            else:
                encode_param = [cv2.IMWRITE_PNG_COMPRESSION, 1]
                ext = '.png'
            
            # 如果是RGB，转换为BGR用于OpenCV
            if len(img.shape) == 3 and img.shape[2] == 3:
                img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            else:
                img_bgr = img
            
            success, encoded = cv2.imencode(ext, img_bgr, encode_param)
            if not success:
                raise RuntimeError(f"Image encoding failed: {self.image_type}")
            return encoded.tobytes()
        else:
            return img.tobytes()
    
    def get_total(self) -> int:
        """Get total number of frames in the file"""
        if not self.save_path.exists():
            return 0

        info = self.get_info()
        if info['exists'] != True:
            return 0

        self.width = info['width']
        self.height = info['height']
        return info['frame_count']
    
    def get_frame(self, frame_num: int) -> Tuple[float, np.ndarray, Dict[str, Any]]:
        """Extract frame data
        
        Args:
            frame_num: Frame number (starting from 0)
            
        Returns:
            (time, img, data): Timestamp, image data, structured data
        """
        if not self.save_path.exists():
            raise FileNotFoundError(f"Data package file does not exist: {self.save_path}")
        
        # Read index
        if self._index_cache is None:
            self._read_index()
        
        if frame_num < 0 or frame_num >= len(self._index_cache):
            raise IndexError(f"Frame number out of range: {frame_num}, total frames: {len(self._index_cache)}")
        
        index_entry = self._index_cache[frame_num]
        
        # Read metadata (read first, as image decoding may need dimension info)
        if self._trace_cache is None:
            self._read_trace()
        
        data = self._trace_cache[frame_num] if frame_num < len(self._trace_cache) else {}
        
        # Read image data
        with open(self.save_path, 'rb') as f:
            f.seek(index_entry['image_offset'])
            img_size = struct.unpack('<I', f.read(4))[0]
            img_bytes = f.read(img_size)
        
        # Decode image (pass metadata to get dimension info)
        img = self._decode_image(img_bytes, self.image_type, data)
        
        # Convert timestamp from microseconds to seconds
        time = index_entry['timestamp'] / 1e6
        
        return time, img, data
    
    def _read_index(self):
        info = self.get_info()

        self.width = info['width']
        self.height = info['height']
        frame_count = info['frame_count']
        index_offset = info['index_offset']
        image_offset = info['image_offset']
        trace_offset = info['trace_offset']

        with open(self.save_path, 'rb') as f:  
            f.seek(index_offset)
            self._index_cache = []
            for i in range(frame_count):
                entry_bytes = f.read(self.INDEX_ENTRY_SIZE)
                timestamp, image_offset_rel, image_size, trace_offset_rel, trace_size = struct.unpack(self.STRUCT_INDEX_FORMAT, entry_bytes)
                
                self._index_cache.append({
                    'timestamp':    timestamp,
                    'image_offset': image_offset + image_offset_rel,  # Absolute offset
                    'image_size':   image_size,
                    'trace_offset': trace_offset + trace_offset_rel,  # Absolute offset
                    'trace_size':   trace_size,
                })
    
    def _read_trace(self):
        """Read metadata into cache"""
        if self._index_cache is None:
            self._read_index()
        
        with open(self.save_path, 'rb') as f:
            self._trace_cache = []
            for index_entry in self._index_cache:
                f.seek(index_entry['trace_offset'])
                trace_size = struct.unpack('<I', f.read(4))[0]
                trace_bytes = f.read(trace_size)
                print("trace:", trace_size)
                trace_json = trace_bytes.decode('utf-8')
                data = json.loads(trace_json)
                self._trace_cache.append(data)
    
    def _decode_image(self, img_bytes: bytes, image_type: str, metadata: Optional[Dict] = None) -> np.ndarray:
        """Decode image data
        
        Args:
            img_bytes: Image byte data
            image_type: Image type
            metadata: Metadata (contains dimension info, optional)
        """
        if image_type == 'nv12':
            # NV12 format: use width and height from file header
            if self.width > 0 and self.height > 0:
                img_array = np.frombuffer(img_bytes, dtype=np.uint8)
                # NV12 format: Y plane + UV interleaved
                return img_array.reshape((self.height * 3 // 2, self.width))
            elif metadata and 'width' in metadata and 'height' in metadata:
                # Fallback: get from metadata
                width = metadata['width']
                height = metadata['height']
                img_array = np.frombuffer(img_bytes, dtype=np.uint8)
                return img_array.reshape((height * 3 // 2, width))
            else:
                # If dimensions unknown, return raw byte array
                print("Warning: NV12 format requires width and height info, but not found")
                return np.frombuffer(img_bytes, dtype=np.uint8)
        elif image_type in ['rgb', 'bgr']:
            # RGB/BGR format: use width and height from file header
            if self.width > 0 and self.height > 0:
                img_array = np.frombuffer(img_bytes, dtype=np.uint8)
                return img_array.reshape((self.height, self.width, 3))
            elif metadata and 'img_shape' in metadata:
                # Fallback: get from metadata
                shape = tuple(metadata['img_shape'])
                img_array = np.frombuffer(img_bytes, dtype=np.uint8)
                return img_array.reshape(shape)
            else:
                # If shape unknown, return raw byte array
                print(f"Warning: {image_type.upper()} format requires width and height info, but not found")
                return np.frombuffer(img_bytes, dtype=np.uint8)
        elif image_type in ['png', 'jpg', 'jpeg']:
            # Decode image
            img_array = np.frombuffer(img_bytes, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is None:
                raise RuntimeError(f"Image decoding failed: {image_type}")
            # Convert to RGB
            if image_type in ['jpg', 'jpeg', 'png']:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            return img
        else:
            # Other formats: return raw byte array
            return np.frombuffer(img_bytes, dtype=np.uint8)
    
    def get_info(self) -> Dict[str, Any]:
        """Get data package information"""
        if not self.save_path.exists():
            return {
                'exists': False,
                'image_type': self.image_type,
                'width': self.width,
                'height': self.height,
                'frame_count': 0
            }
        
        # Read header
        with open(self.save_path, 'rb') as f:
            header = f.read(self.HEADER_SIZE)
            magic, version, image_type, width, height, frame_count, header_size, index_offset, image_offset, trace_offset = self.__class__.decode_header(header)
            
            # Update instance width and height
            self.width = width
            self.height = height
        
        # Get file size
        file_size = self.save_path.stat().st_size
        
        return {
            'exists': True,
            'image_type': image_type,
            'width': width,
            'height': height,
            'frame_count': frame_count,
            'version': version,
            'file_size': file_size,
            'index_offset': index_offset,
            'image_offset': image_offset,
            'trace_offset': trace_offset,
        }

    def get_struct(self) -> Dict[str, Any]:
        """Extract structured information of the data package
        
        Returns:
            Dictionary containing structured package information
        """
        info = self.get_info()
        
        if not info['exists']:
            return {
                'file_path': str(self.save_path),
                'exists': False,
                'status': 'File does not exist'
            }
        
        # Calculate section sizes
        frame_count = info['frame_count']
        index_size = frame_count * self.INDEX_ENTRY_SIZE
        
        # Calculate actual section sizes
        image_section_size = 0
        trace_section_size = 0
        if frame_count > 0:
            image_section_size = info['trace_offset'] - info['image_offset']
            trace_section_size = info['file_size'] - info['trace_offset']
        
        # Load index if needed for frame details
        frame_details = []
        if frame_count > 0:
            if self._index_cache is None:
                try:
                    self._read_index()
                except:
                    pass
            
            if self._index_cache and len(self._index_cache) > 0:
                for i, entry in enumerate(self._index_cache):
                    frame_details.append({
                        'frame_num': i,
                        'timestamp': entry['timestamp'] / 1e6,  # Convert to seconds
                        'image_offset': entry['image_offset'],
                        'image_size': entry['image_size'],
                        'trace_offset': entry['trace_offset'],
                        'trace_size': entry['trace_size']
                    })
        
        # Build structured data
        struct_data = {
            'file': {
                'path': str(self.save_path),
                'name': self.save_path.name,
                'size_bytes': info['file_size'],
                'size_mb': info['file_size'] / 1024 / 1024,
                'version': info['version'],
                'magic': self.MAGIC.decode('utf-8', errors='ignore')
            },
            'image': {
                'type': info['image_type'].upper(),
                'width': info['width'],
                'height': info['height'],
                'total_pixels': info['width'] * info['height']
            },
            'frames': {
                'total': frame_count,
                'avg_size_bytes': (image_section_size + trace_section_size) / frame_count if frame_count > 0 else 0,
                'details': frame_details[:10] if len(frame_details) > 10 else frame_details,  # Limit to first 10
                'has_more': len(frame_details) > 10
            },
            'sections': {
                'header': {
                    'offset': 0,
                    'size': self.HEADER_SIZE
                },
                'index': {
                    'offset': info['index_offset'],
                    'size': index_size,
                    'entry_count': frame_count,
                    'entry_size': self.INDEX_ENTRY_SIZE
                },
                'image': {
                    'offset': info['image_offset'],
                    'size': image_section_size,
                    'avg_per_frame': image_section_size / frame_count if frame_count > 0 else 0
                },
                'trace': {
                    'offset': info['trace_offset'],
                    'size': trace_section_size,
                    'avg_per_frame': trace_section_size / frame_count if frame_count > 0 else 0
                }
            }
        }
        
        return struct_data
    
    def print_struct(self, struct_data: Optional[Dict[str, Any]] = None):
        """Print standardized structure information in formatted format
        
        Args:
            struct_data: Optional structured data from get_struct(). If None, will call get_struct().
        """
        if struct_data is None:
            struct_data = self.get_struct()
        
        if not struct_data.get('exists', True):
            print(f"""
Data Package Structure: {struct_data.get('file_path', 'Unknown')}
Status: {struct_data.get('status', 'Unknown')}
""")
            return
        
        lines = []
        lines.append("=" * 70)
        lines.append(f"Data Package Structure: {struct_data['file']['name']}")
        lines.append("=" * 70)
        lines.append("")
        
        # File Information
        lines.append("File Information:")
        lines.append(f"  Path:              {struct_data['file']['path']}")
        lines.append(f"  Size:              {struct_data['file']['size_bytes']:,} bytes ({struct_data['file']['size_mb']:.2f} MB)")
        lines.append(f"  Version:           {struct_data['file']['version']}")
        lines.append(f"  Magic:             {struct_data['file']['magic']}")
        lines.append("")
        
        # Image Information
        lines.append("Image Information:")
        lines.append(f"  Type:              {struct_data['image']['type']}")
        lines.append(f"  Dimensions:        {struct_data['image']['width']} x {struct_data['image']['height']} pixels")
        lines.append(f"  Total Pixels:      {struct_data['image']['total_pixels']:,}")
        lines.append("")
        
        # Frame Information
        lines.append("Frame Information:")
        lines.append(f"  Total Frames:      {struct_data['frames']['total']}")
        if struct_data['frames']['total'] > 0:
            lines.append(f"  Avg Frame Size:    {struct_data['frames']['avg_size_bytes']:,.0f} bytes")
        lines.append("")
        
        # File Structure
        lines.append("File Structure:")
        lines.append(f"  Header Section:")
        lines.append(f"    Offset:          {struct_data['sections']['header']['offset']}")
        lines.append(f"    Size:            {struct_data['sections']['header']['size']} bytes")
        lines.append("")
        lines.append(f"  Index Section:")
        lines.append(f"    Offset:          {struct_data['sections']['index']['offset']:,} bytes")
        lines.append(f"    Size:            {struct_data['sections']['index']['size']:,} bytes ({struct_data['sections']['index']['entry_count']} entries × {struct_data['sections']['index']['entry_size']} bytes)")
        lines.append("")
        lines.append(f"  Image Section:")
        lines.append(f"    Offset:          {struct_data['sections']['image']['offset']:,} bytes")
        lines.append(f"    Size:            {struct_data['sections']['image']['size']:,} bytes")
        if struct_data['frames']['total'] > 0:
            lines.append(f"    Avg per Frame:   {struct_data['sections']['image']['avg_per_frame']:,.0f} bytes")
        lines.append("")
        lines.append(f"  Trace Section:")
        lines.append(f"    Offset:          {struct_data['sections']['trace']['offset']:,} bytes")
        lines.append(f"    Size:            {struct_data['sections']['trace']['size']:,} bytes")
        if struct_data['frames']['total'] > 0:
            lines.append(f"    Avg per Frame:   {struct_data['sections']['trace']['avg_per_frame']:,.0f} bytes")
        lines.append("")
        
        # Index Entries (show details if available)
        if struct_data['frames']['details']:
            lines.append("Index Entries (first 10):")
            for frame_detail in struct_data['frames']['details']:
                lines.append(f"  Frame {frame_detail['frame_num']}:")
                lines.append(f"    Timestamp:       {frame_detail['timestamp']:.6f} s")
                lines.append(f"    Image Offset:    {frame_detail['image_offset']:,} bytes")
                lines.append(f"    Image Size:      {frame_detail['image_size']:,} bytes")
                lines.append(f"    Trace Offset:    {frame_detail['trace_offset']:,} bytes")
                lines.append(f"    Trace Size:      {frame_detail['trace_size']:,} bytes")
            if struct_data['frames']['has_more']:
                remaining = struct_data['frames']['total'] - len(struct_data['frames']['details'])
                lines.append(f"  ... ({remaining} more frames)")
            lines.append("")
        
        lines.append("=" * 70)
        
        print("\n".join(lines))
    
    @classmethod
    def open(cls, file_path: str) -> 'DataPackage':
        """Open an existing data package file"""
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"Data package does not exist: {file_path}")

        # Read file header to get image type and dimensions
        with open(file_path, 'rb') as f:
            header = f.read(cls.HEADER_SIZE)
            if len(header) < cls.HEADER_SIZE:
                raise ValueError(f"Header too small: {len(header)} bytes")

            magic, version, image_type, width, height, frame_count, header_size, index_offset, image_offset, trace_offset = cls.decode_header(header)
        
        # Create instance (pass width and height)
        package = cls(str(file_path), image_type, width=width, height=height)
        return package




if __name__ == '__main__':
    import time
    """Test data package"""
    
    # Clean up old file
    test_file = 'tmp/test.dat'
    if os.path.exists(test_file):
        os.remove(test_file)
    
    # Initialize (need to provide width and height)
    width, height = 1920, 1088
    package = DataPackage(test_file, image_type='nv12', width=width, height=height, realtime=True)
    package.start_recording()

    for i in range(30):
        print(f"Add frame {i}")
        # Add NV12 data
        nv12_size = width * height * 3 // 2
        nv12_data = np.zeros(nv12_size, dtype=np.uint8)
        package.add_frame(i, nv12_data, trace={'path': np.random.rand(10).tolist()})
        time.sleep(3)
        
    # Save
    package.save()

    print("Load Test")

    # Get structured data
    struct_data = package.get_struct()
    
    # Print formatted structure
    package.print_struct(struct_data)
    
    # Test various methods
    frame_count = package.get_total()
    print(f"Frame count: {frame_count}")
    
    time, img, data = package.get_frame(frame_count-1)
    print(f"Read frame: time={time:.3f}, img_shape={img.shape}, data={data}")
    
    info = package.get_info()
    print(f"Info: {info}")
    
    # Test loading
    package2 = DataPackage.open(test_file)
    info2 = package2.get_info()
    print(f"Info after loading: {info2}")
    assert info2['width'] == width, f"Width mismatch: {info2['width']} != {width}"
    assert info2['height'] == height, f"Height mismatch: {info2['height']} != {height}"
    
    print("Test passed!")