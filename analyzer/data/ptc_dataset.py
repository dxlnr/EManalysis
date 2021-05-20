import os, sys
import random

import numpy as np
import h5py
from scipy import stats
from sklearn.preprocessing import normalize
from tqdm import tqdm
from sklearn.metrics import pairwise_distances
import multiprocessing as mp


def normalize_ptc(ptc):
    '''
    Function normalizes the ptc (Nxd) by min-max-scaling.
    :param ptc: (np.ndarray) size: Nxd
    '''
    return normalize(ptc, axis=0, norm='max')

def rotate_point_cloud(batch_data):
    '''
    Randomly rotate the point clouds to augument the dataset rotation is per shape based along up direction
    '''
    #TODO
    '''
    rotated_data = np.zeros(batch_data.shape, dtype=np.float32)
    for k in xrange(batch_data.shape[0]):
        rotation_angle = np.random.uniform() * 2 * np.pi
        cosval = np.cos(rotation_angle)
        sinval = np.sin(rotation_angle)
        rotation_matrix = np.array([[cosval, 0, sinval],
                                    [0, 1, 0],
                                    [-sinval, 0, cosval]])
        shape_pc = batch_data[k, ...]
        rotated_data[k, ...] = np.dot(shape_pc.reshape((-1, 3)), rotation_matrix)
    return rotated_data
    '''
    pass

class PtcDataset():
    '''
    This is the Data module for the pointcloud autoencoder.
    '''
    def __init__(self, cfg, sample_size=2000, sample_mode=None):
        self.cfg = cfg
        self.sample_size = sample_size
        self.ptfn = cfg.DATASET.ROOTD + 'vae/pts' + '.h5'
        self.sample_mode = sample_mode
        self.dists = {}
        self.blue_noise_sample_points = cfg.AUTOENCODER.BLUE_NOISE_SAMPLE_POINTS
        if sample_mode == 'montecarlo':
            self.rptcfn = cfg.DATASET.ROOTD+ 'vae/random_ptc' + '.h5'
            if os.path.exists(self.rptcfn):
                return
            print("calculating random points via monte carlo sampling")
            with h5py.File(self.ptfn, 'r') as h5f:
                with h5py.File(self.rptcfn, 'w') as random_points_file:
                    group = h5f.get('ptcs')
                    for idx in tqdm(group.keys(), total=len(group.keys())):
                        cloud = np.array(group[idx])
                        centroid = np.mean(cloud, axis=0)
                        dists = []
                        for point in cloud:
                            dists.append(np.linalg.norm(point-centroid))
                        dists /= sum(dists)
                        xk = np.arange(len(dists))
                        custm = stats.rv_discrete(name='custm', values=(xk, dists))
                        random_points = cloud[custm.rvs(size=self.sample_size), :]
                        random_points_file[idx] = random_points

        if sample_mode == "bluenoise":
            self.rptcfn = cfg.DATASET.ROOTD + 'vae/random_ptc' + '.h5'
            if os.path.exists(self.rptcfn):
                return
            print("calculating random points via bluenoise sampling")

            with h5py.File(self.rptcfn, 'w') as random_points_file:
                with h5py.File(self.ptfn, 'r') as h5f:
                    group = h5f.get('ptcs')
                    pool = mp.Pool(processes=cfg.SYSTEM.NUM_CPUS)
                    results = [pool.apply(self.calculate_blue_noise_samples, args=(key,)) for key in tqdm(group.keys(), total=len(group.keys()))]
                    for result in results:
                        random_points[result[0]] = result[1]

    def calculate_blue_noise_samples(self, key):
        with h5py.File(self.ptfn, 'r') as h5f:
            group = h5f.get('ptcs')
            cloud = np.array(group[key])
        idxs = []
        # dists = pairwise_distances(points)
        possible_idx = list(np.arange(0, len(cloud)))
        start = random.sample(possible_idx, 1)[0]
        possible_idx.pop(start)
        idxs.append(start)
        for i in range(1, self.sample_size):
            if len(possible_idx) < self.blue_noise_sample_points:
                possible_idx = list(np.arange(0, len(cloud)))
            candidates = random.sample(possible_idx, self.blue_noise_sample_points)
            best_candidate = -1
            best_dist = 0
            for c in candidates:
                for point in idxs:
                    new_dist = np.linalg.norm(cloud[c] - cloud[point])
                    if best_dist < new_dist:
                        best_dist = new_dist
                        best_candidate = c

            possible_idx.remove(best_candidate)
            idxs.append(best_candidate)
        idxs = sorted(idxs)
        random_points = cloud[idxs, :]
        return key, random_points

    def __len__(self):
        '''
        Required by torch to return the length of the dataset.
        :returns: integer
        '''
        with h5py.File(self.ptfn, 'r') as h5f:
            return len(list(h5f.get('ptcs').keys()))

    def __getitem__(self, idx):
        '''
        Required by torch to return one item of the dataset.
        :param idx: (int) index of the object. Please note that this is the actual label e.g. 1325 not a pure index like 0,1,2, ... ,n
        :returns: object from the volume. (np.array)
        '''
        with h5py.File(self.ptfn, 'r') as h5f:
            group = h5f.get('ptcs')
            idx = sorted(list(group.keys()))[idx]
            ptc = np.array(group[idx])
            if self.sample_mode == 'partial':
                if ptc.shape[0] > self.sample_size:
                    randome_indices = np.random.random_integers(ptc.shape[0] - 1, size=(self.sample_size))
                    return np.expand_dims(ptc[randome_indices, :], axis=0), idx
            elif self.sample_mode == 'full':
                with h5py.File(self.rptcfn, 'r') as random_points_file:
                    return np.expand_dims(random_points_file[str(idx)], axis=0), idx
            return np.expand_dims(ptc, axis=0), idx

    @property
    def keys(self):
        '''property that gives to a list of keys (ints) that are in the dataset.
        '''
        with h5py.File(self.ptfn, 'r') as h5f:
            return list(map(int, list(h5f.get('ptcs').keys())))

    @property
    def dimlist(self):
        '''returns list of number of points that every point cloud contains.'''
        dim_list = list()
        with h5py.File(self.ptfn, 'r') as h5f:
            group = h5f.get('ptcs')
            for _, idx in enumerate(list(h5f.get('ptcs').keys())):
                dim_list.append(np.array(group[str(idx)]).shape[0])
        return dim_list

    def split_dataset(self):
        '''split dataset and keep order (avoid loss of label information).'''
        pass

    def recur(self, group, idx):
        '''helper to overcome a missed label'''
        if str(idx) in list(group.keys()):
            tmp = np.array(group[str(idx)])
            return tmp, idx
        else:
            idx = idx + 1
            tmp, idx = self.recur(group, idx)
            return tmp, idx

    def save_cloud_vis(self, cloud, random_cloud):
        pass