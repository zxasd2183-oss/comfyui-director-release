"""Real RGBA PNG byte contract for the 1MiB Director Hub MCP transport.

No PIL, real GPU, browser, arbitrary URLs, or root services required.
"""
import binascii
import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ue_worker_rpc import (WorkerError, PNG_HEADER,
                           make_bounded_preview_thumbnail_png)

def chunk(name, body):
    return (struct.pack(">I",len(body))+name+body+
            struct.pack(">I",binascii.crc32(name+body)&0xffffffff))

def original_png(channels=4):
    width,height=720,1280
    # Different source pixel values at each source row and x, with all
    # five PNG scanline filter types exercised independently.
    rows=[]
    filtered=[]
    prev=bytes(width*channels)
    for y in range(height):
        row=bytes((x+y*7+i*29)&255
                  for x in range(width) for i in range(channels))
        method=y%5
        encoded=bytearray(width*channels)
        for i,raw in enumerate(row):
            left=row[i-channels] if i>=channels else 0
            above=prev[i]
            ul=prev[i-channels] if i>=channels else 0
            if method==0: predictor=0
            elif method==1: predictor=left
            elif method==2: predictor=above
            elif method==3: predictor=(left+above)//2
            else:
                p=left+above-ul
                a,b,c=abs(p-left),abs(p-above),abs(p-ul)
                predictor=left if a<=b and a<=c else (above if b<=c else ul)
            encoded[i]=(raw-predictor)&255
        filtered.append(bytes([method])+bytes(encoded))
        prev=row
        if y%2==0: rows.append(row)
    png=(PNG_HEADER+
         chunk(b"IHDR",struct.pack(">IIBBBBB",720,1280,8,
                                  6 if channels==4 else 2,0,0,0))+
         chunk(b"IDAT",zlib.compress(b"".join(filtered),level=6))+
         chunk(b"IEND",b""))
    return png,rows

def read_unfiltered_thumbnail(png):
    w,h=struct.unpack(">II",png[16:24])
    channels=4 if png[25]==6 else 3
    pos=8
    compressed=b""
    while pos+12<=len(png):
        size=struct.unpack_from(">I",png,pos)[0]
        name=png[pos+4:pos+8]
        if name==b"IDAT":
            compressed+=png[pos+8:pos+8+size]
        pos+=12+size
    data=zlib.decompress(compressed)
    return (w,h,channels,data)

class BridgeThumbnailTest(unittest.TestCase):
    def test_actual_rgba_png_filters_and_sha_safe_thumbnail(self):
        source,rows=original_png(4)
        self.assertGreater(len(source),2048)
        preview=make_bounded_preview_thumbnail_png(source)
        self.assertLessEqual(len(preview),512*1024)
        self.assertTrue(preview.startswith(PNG_HEADER))
        w,h,channels,data=read_unfiltered_thumbnail(preview)
        self.assertEqual((w,h,channels),(360,640,4))
        self.assertEqual(len(data),h*(1+w*channels))
        for y in (0,1,207,639):
            self.assertEqual(data[y*(1+w*channels)],0)
            for x in (0,1,103,359):
                start=y*(1+w*channels)+1+x*channels
                self.assertEqual(data[start:start+channels],
                                 rows[y][(x*2)*channels:(x*2+1)*channels])

    def test_rgb_and_corrupted_digest_chunk_are_rejected(self):
        source,_=original_png(3)
        thumb=make_bounded_preview_thumbnail_png(source)
        self.assertLessEqual(len(thumb),512*1024)
        self.assertEqual(thumb[25],2)
        corrupted=bytearray(source)
        corrupted[-1]^=1
        with self.assertRaises(WorkerError):
            make_bounded_preview_thumbnail_png(bytes(corrupted))
        with self.assertRaises(WorkerError):
            make_bounded_preview_thumbnail_png(b"not a png")

if __name__=="__main__":
    unittest.main()
