import numpy as np
import pandas as pd

def calc_bollinger_bands(df, window=20, num_of_std=2):
    """
    计算布林带
    :param df: pandas DataFrame, 需包含 'close' 列
    :param window: 移动平均周期，默认 20
    :param num_of_std: 标准差倍数，默认 2
    """
    # ...
