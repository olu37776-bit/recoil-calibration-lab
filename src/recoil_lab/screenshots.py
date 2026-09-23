"""Offline screenshot measurements. Static images never become timed recoil curves."""
from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
import warnings
import numpy as np

from .contracts import CalibrationError, Trial, context_id, digest

MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_PIXELS = 12_000_000
MAX_SEQUENCE_PIXELS = 90_000_000


def decode_image(encoded: str) -> tuple[np.ndarray, str]:
    """Decode explicitly supplied image bytes, not a URL or server-side path."""
    from PIL import Image
    if not isinstance(encoded,str) or len(encoded)>MAX_IMAGE_BYTES*4//3+256:
        raise CalibrationError("图片过大或格式无效")
    if encoded.startswith("data:"):
        header,sep,encoded=encoded.partition(",")
        if not sep or header not in {"data:image/png;base64","data:image/jpeg;base64","data:image/webp;base64"}:
            raise CalibrationError("仅接受 PNG、JPEG、WebP 图片")
    try:
        raw=base64.b64decode(encoded, validate=True)
        if not raw or len(raw)>MAX_IMAGE_BYTES:
            raise CalibrationError("图片为空或超过 6 MiB")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                if image.format not in {"PNG","JPEG","WEBP"} or image.width*image.height>MAX_PIXELS:
                    raise CalibrationError("不支持的图片或超过 1200 万像素")
                if getattr(image,"n_frames",1)!=1:
                    raise CalibrationError("不接受动图，请提供明确的单帧")
                if image.width<32 or image.height<32:
                    raise CalibrationError("图片至少为 32×32 像素")
                # Keep original raster coordinates; no implicit EXIF rotation/rescaling.
                array=np.asarray(image.convert("RGB"))[:,:,::-1].copy()
        return array,sha256(raw).hexdigest()
    except CalibrationError:
        raise
    except Exception as exc:
        raise CalibrationError("无法解码图片") from exc


def checked_roi(roi: list, shape: tuple) -> tuple[int,int,int,int]:
    if not isinstance(roi,list) or len(roi)!=4 or any(type(x) is not int for x in roi):
        raise CalibrationError("ROI 必须是 [x,y,width,height] 整数")
    x,y,w,h=roi
    if min(x,y)<0 or min(w,h)<32 or x+w>shape[1] or y+h>shape[0]:
        raise CalibrationError("ROI 越界或小于 32×32")
    return x,y,w,h


def pattern_summary(image: np.ndarray, aim: list, points: list, image_hash: str, context: dict) -> dict:
    context_id(context)
    h,w=image.shape[:2]
    if context["resolution"]!=[w,h]:
        raise CalibrationError("截图尺寸与配装分辨率不同；禁止隐式缩放")
    try:
        a=np.asarray(aim,dtype=float)
        p=np.asarray(points,dtype=float)
    except (TypeError,ValueError) as exc:
        raise CalibrationError("弹着标注坐标无效") from exc
    if a.shape!=(2,) or p.ndim!=2 or p.shape[1]!=2 or not 1<=len(p)<=1000:
        raise CalibrationError("需要一个初始瞄准点和 1～1000 个弹着标注")
    both=np.vstack([a,p])
    if not np.isfinite(both).all() or (both<0).any() or (both[:,0]>=w).any() or (both[:,1]>=h).any():
        raise CalibrationError("标注点必须在原始图片范围内")
    offset=p-a
    centroid=offset.mean(axis=0)
    centered=offset-centroid
    return {"schema_version":1,"kind":"static_pattern","context_id":context_id(context),"context":context,
        "capture_sha256":image_hash,"units":"native_image_px","axes":"x right, y down",
        "marked_impacts":len(p),"aim_px":a.tolist(),"points_px":p.tolist(),
        "centroid_from_aim_px":centroid.tolist(),"bbox_size_px":np.ptp(p,axis=0).tolist(),
        "rms_about_centroid_px":float(np.sqrt((centered**2).sum(axis=1).mean())),
        "rms_from_aim_px":float(np.sqrt((offset**2).sum(axis=1).mean())),
        "can_fit_time_curve":False,"limitations":["标注数量不是实际射击发数；弹孔可能重叠", "未恢复逐发顺序、时间、鼠标输入或后坐力轨迹"]}


def pair_displacement(before: np.ndarray, after: np.ndarray, roi: list, context: dict, hashes: list[str]) -> dict:
    from .video import _cv
    cv=_cv()
    context_id(context)
    if before.shape!=after.shape or context["resolution"]!=[before.shape[1],before.shape[0]]:
        raise CalibrationError("两张图必须等大，并匹配当前配装分辨率")
    x,y,w,h=checked_roi(roi,before.shape)
    a=cv.cvtColor(before,cv.COLOR_BGR2GRAY)
    b=cv.cvtColor(after,cv.COLOR_BGR2GRAY)
    mask=np.zeros(a.shape,np.uint8); mask[y:y+h,x:x+w]=255
    p=cv.goodFeaturesToTrack(a,maxCorners=240,qualityLevel=.02,minDistance=6,mask=mask)
    if p is None or len(p)<12:
        raise CalibrationError("纹理不足；请选墙面而非准星、天空或枪身")
    q,ok,_=cv.calcOpticalFlowPyrLK(a,b,p,None,winSize=(31,31),maxLevel=4)
    if q is None or ok is None:
        raise CalibrationError("无法匹配两张截图")
    r,back,_=cv.calcOpticalFlowPyrLK(b,a,q,None,winSize=(31,31),maxLevel=4)
    if r is None or back is None:
        raise CalibrationError("双向追踪失败")
    p,q,r=p.reshape(-1,2),q.reshape(-1,2),r.reshape(-1,2)
    good=(ok.ravel()==1)&(back.ravel()==1)&(np.linalg.norm(p-r,axis=1)<.8)&np.isfinite(q).all(axis=1)
    good&=(q[:,0]>=x)&(q[:,0]<x+w)&(q[:,1]>=y)&(q[:,1]<y+h)
    shift=q[good]-p[good]
    if len(shift)<12:
        raise CalibrationError("匹配点不足；不能把遮挡或切场景当后坐力")
    median=np.median(shift,axis=0)
    inlier=np.linalg.norm(shift-median,axis=1)<1.25
    quality=float(inlier.sum()/len(p))
    if inlier.sum()<12 or quality<.65 or np.linalg.norm(median)>min(w,h)/4:
        raise CalibrationError("平移模型不可靠：检查移动、变焦、遮挡或两图间隔过长")
    camera=-np.median(shift[inlier],axis=0)
    return {"schema_version":1,"kind":"endpoint_displacement","context":context,"context_id":context_id(context),
        "capture_hashes":hashes,"roi":roi,"camera_delta_px":camera.tolist(),"confidence":quality,
        "units":"native_image_px","axes":"camera x right, y down","can_fit_time_curve":False,
        "limitations":["仅测静态背景反向位移，不证明位移全部来自后坐力", "两张图不提供完整时间轨迹，不生成鼠标输入"]}


def screenshot_sequence(encoded: list[str], timestamps: list, *, roi: list, context: dict,
                        run_id: str, capture_session: str, uncompensated: bool) -> Trial:
    from .contracts import identifier
    from .video import track_frames
    if uncompensated is not True:
        raise CalibrationError("必须确认静止、固定瞄准状态且未执行补偿")
    identifier(capture_session,"capture_session")
    if not isinstance(encoded,list) or not 10<=len(encoded)<=120 or not isinstance(timestamps,list) or len(encoded)!=len(timestamps):
        raise CalibrationError("连续截图需要 10～120 帧及逐帧时间戳")
    frames=[]; hashes=[]; total=0
    for item in encoded:
        image,hashed=decode_image(item)
        total+=image.shape[0]*image.shape[1]
        if total>MAX_SEQUENCE_PIXELS:
            raise CalibrationError("截图序列解码像素总数过大，请缩短片段")
        frames.append(image); hashes.append(hashed)
    checked_roi(roi,frames[0].shape)
    # Names, file order and EXIF are not a trustworthy firing clock.
    try:
        times=np.asarray(timestamps,dtype=float)
    except (ValueError,TypeError) as exc:
        raise CalibrationError("时间戳无效") from exc
    if times.ndim!=1 or not np.isfinite(times).all() or times[0]<0:
        raise CalibrationError("时间戳必须为有限非负秒数")
    return track_frames(zip(times,frames),tuple(roi),context=context,run_id=run_id,
        session_id=capture_session,source="recorded",provenance={"capture_sha256":capture_session,
        "frame_set_sha256":digest(hashes),"frame_sha256":hashes,"timing":"operator_explicit_timestamps",
        "roi":roi,"operator_declaration":"stationary fixed ADS uncompensated",
        "capture_group_note":"同一原始录制的片段必须使用相同 capture_session，不能充当独立验证"})
