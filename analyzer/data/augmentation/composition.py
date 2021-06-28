import numpy as np
from skimage.filters import gaussian

class Compose(object):
    '''Composing a list of data transforms for handling 3d volumes.
    '''
    def __init__(self,
                 transforms: list = []):
        self.transforms = transforms

    def __call__(self):
        pass