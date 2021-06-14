from analyzer.data.augmentation.augmentor import Augmentor

class CLTrainer():
    '''
        Trainer object, enabling constrastive learning framework.
        :params cfg: (yacs.config.CfgNode): YACS configuration options.
    '''
    def __init__(self, cfg):
        self.cfg = cfg
        self.augmentor = Augmentor(cfg)
