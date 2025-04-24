import sys
import os
import time
import multiprocessing
from multiprocessing import cpu_count, Event, Value, Process
import numpy as np
from numba import njit, prange
import secp256k1 as ice

# Configuration
puzzle = 68
min_range = 2 ** (puzzle - 1) - 1
max_range = 2 ** puzzle - 1
START_WIF = "KwDiBf89QgGbjEhKnhXJuH7LrciVrZi3qd7sDG4F"
MISSING_CHARS = 52 - len(START_WIF)
TARGET_HEX = "e0b8a2baee1b77fc703455f39d51477451fc8cfc"
TARGET_BINARY = bytes.fromhex(TARGET_HEX)
BATCH_SIZE = 60000

# Global variables
STOP_EVENT = Event()
KEY_COUNTER = Value('q', 0)
START_TIME = Value('d', 0.0)
CHARS = np.frombuffer(
    b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
    dtype=np.uint8
)
START_BYTES = START_WIF.encode('ascii')  # Precompute this

@njit(cache=True, parallel=True)
def numba_generate_batch(start_bytes, miss, batch_size, chars):
    results = np.empty((batch_size, len(start_bytes) + miss), dtype=np.uint8)
    char_len = len(chars)
    for i in prange(batch_size):
        # Copy the fixed prefix
        results[i, :len(start_bytes)] = start_bytes
        # Generate random suffix with indices within bounds
        for j in range(miss):
            results[i, len(start_bytes)+j] = np.random.randint(0, char_len)
    return results

def generate_batch(batch_size):
    indices = numba_generate_batch(
        np.frombuffer(START_BYTES, dtype=np.uint8),
        MISSING_CHARS,
        batch_size,
        CHARS
    )
    return [START_BYTES + CHARS[indices[i, -MISSING_CHARS:]].tobytes()
            for i in range(batch_size)]

def check_private_key_batch(target_binary):
    local_counter = 0
    
    while not STOP_EVENT.is_set():
        # Generate a batch of keys
        wif_batch = generate_batch(BATCH_SIZE)
        local_counter += BATCH_SIZE
        
        # Update global counter
        with KEY_COUNTER.get_lock():
            KEY_COUNTER.value += BATCH_SIZE
        
        # Process the batch
        for wif_bytes in wif_batch:
            if STOP_EVENT.is_set():
                break
                
            try:
                private_key_hex = ice.btc_wif_to_pvk_hex(wif_bytes.decode('ascii'))
                dec = int(private_key_hex, 16)
                if min_range <= dec <= max_range:
                     ripemd160_hash = ice.privatekey_to_h160(0, True, dec)
                
                     if ripemd160_hash == target_binary:
                         handle_success(dec)
                         return
                    
            except:
                continue
    
    # Add any remaining keys if we were interrupted
    with KEY_COUNTER.get_lock():
        KEY_COUNTER.value += local_counter % BATCH_SIZE

def handle_success(dec):
    t = time.ctime()
    wif_compressed = ice.btc_pvk_to_wif(dec)
    elapsed = time.time() - START_TIME.value
    
    with open('winner.txt', 'a') as f:
        f.write(f"\n\nMatch Found: {t}")
        f.write(f"\nPrivatekey (dec): {dec}")
        f.write(f"\nPrivatekey (hex): {hex(dec)[2:]}")
        f.write(f"\nPrivatekey (wif): {wif_compressed}")
        f.write(f"\nTotal keys checked: {KEY_COUNTER.value:,}")
        f.write(f"\nAverage speed: {KEY_COUNTER.value/elapsed:,.0f} keys/sec")
    
    STOP_EVENT.set()
    print(f"\n\033[01;33m[+] BINGO!!! {t}\n")

if __name__ == '__main__':
    os.system("clear")
    print(f"\033[01;33m[+] {time.ctime()}")
    print(f"[+] Missing chars: {MISSING_CHARS}")
    print(f"[+] Target: {TARGET_HEX}")
    print(f"[+] Starting WIF: {START_WIF}")
    print(f"[+] Cores: {cpu_count()}")
    
    # Initialize START_TIME
    START_TIME.value = time.time()
    
    try:
        os.nice(-15)
        import psutil
        p = psutil.Process()
        p.cpu_affinity(list(range(cpu_count())))
    except:
        pass

    workers = []
    for _ in range(cpu_count()):
        p = Process(target=check_private_key_batch, args=(TARGET_BINARY,))
        p.start()
        workers.append(p)
    
    try:
        while not STOP_EVENT.is_set():
            time.sleep(1)
            current_count = KEY_COUNTER.value
            elapsed = max(time.time() - START_TIME.value, 0.0001)
            speed = current_count / elapsed
            sys.stdout.write(f"\r[+] Speed: {speed:,.0f} keys/sec | Total: {current_count:,} keys")
            sys.stdout.flush()
    except KeyboardInterrupt:
        STOP_EVENT.set()
        print("\n[!] Stopping workers...")
    
    for p in workers:
        p.join()
    
    print(f"\nSearch completed. Final count: {KEY_COUNTER.value:,} keys")