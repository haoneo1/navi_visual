from pyper.viper_classes import PolhemusViper
from threading import Event
from multiprocessing.pool import ThreadPool
import time

viper = PolhemusViper()
viper.connect()
viper.start_continuous(pno_mode="acceleration", frame_counting="reset_frames") # "reset_frames" means that the first frame after starting the continuous mode will have an index == 0

stop_event = Event()
pool = ThreadPool(processes=1)
async_result = pool.apply_async(viper.read_continuous, [stop_event])

time.sleep(2)


stop_event.set()
result = async_result.get()

viper.stop_continuous()

print(result)

