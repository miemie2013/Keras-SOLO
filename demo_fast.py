#! /usr/bin/env python
# coding=utf-8
# ================================================================
#
#   Author      : miemie2013
#   Created date: 2020-06-22 12:06:26
#   Description : keras_solo
#
# ================================================================
from collections import deque
import datetime
import cv2
import os
import colorsys
import random
import time
import numpy as np
import tensorflow as tf
import keras
import keras.layers as layers
from scipy import ndimage

from config import DecoupledSOLO_R50_FPN_Config
from model.head import DecoupledSOLOHead
from model.neck import FPN
from model.resnet import Resnet
from model.solo import SOLO
from tools.cocotools import get_classes

import logging
FORMAT = '%(asctime)s-%(levelname)s: %(message)s'
logging.basicConfig(level=logging.INFO, format=FORMAT)
logger = logging.getLogger(__name__)



def process_image(img, input_shape):
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = img.shape[:2]
    scale_x = float(input_shape[1]) / w
    scale_y = float(input_shape[0]) / h
    img = cv2.resize(img, None, None, fx=scale_x, fy=scale_y, interpolation=cv2.INTER_CUBIC)

    mean = [123.675, 116.28, 103.53]
    std = [58.395, 57.12, 57.375]
    mean = np.array(mean)[np.newaxis, np.newaxis, :]
    std = np.array(std)[np.newaxis, np.newaxis, :]
    pimage = img.astype(np.float32)
    pimage -= mean
    pimage /= std
    pimage = np.expand_dims(pimage, axis=0)
    return pimage


def draw(image, scores, classes, masks, all_classes, mask_alpha=0.45):
    image_h, image_w, _ = image.shape

    for score, cl, ms in zip(scores, classes, masks):
        center_y, center_x = ndimage.measurements.center_of_mass(ms)  # 求物体掩码的质心。scipy提供技术支持。

        cl = int(cl)

        # 随机颜色
        # bbox_color = random.choice(colors)
        # 同一类别固定颜色
        bbox_color = colors[cl]


        # 在这里上掩码颜色
        color = np.array(bbox_color)
        color = np.reshape(color, (1, 1, 3))
        ms = np.expand_dims(ms, axis=2)
        ms = np.tile(ms, (1, 1, 3))
        color_ms = ms * color * mask_alpha
        color_im = ms * image * (1 - mask_alpha)
        image = color_im + color_ms + (1 - ms) * image

        # 类别、得分
        center_x = max(0, np.floor(center_x + 0.5).astype(int))
        center_y = max(0, np.floor(center_y + 0.5).astype(int))
        bbox_mess = '%s: %.2f' % (all_classes[cl], score)
        cv2.putText(image, bbox_mess, (center_x, center_y - 2), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 0, 0), 1, lineType=cv2.LINE_AA)
    return image




# 6G的卡，训练时如果要预测，则设置use_gpu = False，否则显存不足。
use_gpu = False
use_gpu = True

# 显存分配。
if use_gpu:
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
else:
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
from keras.backend.tensorflow_backend import set_session
config = tf.ConfigProto()
config.gpu_options.per_process_gpu_memory_fraction = 1.0
set_session(tf.Session(config=config))

if __name__ == '__main__':
    cfg = DecoupledSOLO_R50_FPN_Config()

    classes_path = 'data/coco_classes.txt'
    # model_path可以是'solo.h5'、'./weights/step00001000.h5'这些。
    # model_path = 'solo.h5'
    model_path = './weights/step00002000.h5'

    # input_shape越大，精度会上升，但速度会下降。
    # input_shape = (672, 672)
    # input_shape = (416, 416)
    input_shape = (800, 800)

    # 是否给图片画框。不画可以提速。读图片、后处理还可以继续优化。
    draw_image = True
    # draw_image = False


    all_classes = get_classes(classes_path)
    num_classes = len(all_classes)

    inputs = layers.Input(shape=(None, None, 3))
    resnet = Resnet(50)
    fpn = FPN(in_channels=[256, 512, 1024, 2048], out_channels=256, num_outs=5)
    head = DecoupledSOLOHead()
    solo = SOLO(resnet, fpn, head)
    outs = solo(inputs, cfg, eval=True)
    # outs = solo(inputs, cfg, eval=False)
    solo = keras.models.Model(inputs=inputs, outputs=outs)
    solo.load_weights(model_path, by_name=True)

    # 定义颜色
    hsv_tuples = [(1.0 * x / num_classes, 1., 1.) for x in range(num_classes)]
    colors = list(map(lambda x: colorsys.hsv_to_rgb(*x), hsv_tuples))
    colors = list(map(lambda x: (int(x[0] * 255), int(x[1] * 255), int(x[2] * 255)), colors))
    random.seed(0)
    random.shuffle(colors)
    random.seed(None)


    path_dir = os.listdir('images/test')
    # warm up
    if use_gpu:
        for k, filename in enumerate(path_dir):
            image = cv2.imread('images/test/' + filename)
            pimage = process_image(np.copy(image), input_shape)
            outs = solo.predict(pimage)
            if k == 10:
                break


    time_stat = deque(maxlen=20)
    start_time = time.time()
    end_time = time.time()
    num_imgs = len(path_dir)
    start = time.time()
    for k, filename in enumerate(path_dir):
        image = cv2.imread('images/test/' + filename)
        pimage = process_image(np.copy(image), input_shape)
        outs = solo.predict(pimage)
        masks, classes, scores = outs[0][0], outs[1][0], outs[2][0]
        h, w, _ = image.shape
        # 后处理那里，一定不会返回空。若没有物体，scores[0]会是负数，由此来判断有没有物体。
        if scores[0] > 0:
            masks = masks.transpose(1, 2, 0)
            masks = cv2.resize(masks, (w, h), interpolation=cv2.INTER_LINEAR)
            masks = np.reshape(masks, (h, w, -1))
            masks = masks.transpose(2, 0, 1)
            masks = (masks > 0.5).astype(np.float32)
            if draw_image:
                image = draw(image, scores, classes, masks, all_classes)

        # 估计剩余时间
        start_time = end_time
        end_time = time.time()
        time_stat.append(end_time - start_time)
        time_cost = np.mean(time_stat)
        eta_sec = (num_imgs - k) * time_cost
        eta = str(datetime.timedelta(seconds=int(eta_sec)))

        logger.info('Infer iter {}, num_imgs={}, eta={}.'.format(k, num_imgs, eta))
        if draw_image:
            cv2.imwrite('images/res/' + filename, image)
            logger.info("Detection bbox results save in images/res/{}".format(filename))
    cost = time.time() - start
    logger.info('total time: {0:.6f}s'.format(cost))
    logger.info('Speed: %.6fs per image,  %.1f FPS.'%((cost / num_imgs), (num_imgs / cost)))


