import glob
import json
import math
import multiprocessing
import os

import h5py
import imageio
import numpy as np
import pandas as pd
from numpyencoder import NumpyEncoder
from skimage.measure import label, regionprops
from skimage.transform import resize
from sklearn.cluster import KMeans
from tqdm import tqdm

from analyzer.data.data_raw import readvol, folder2Vol


class Dataloader():
    '''
    Dataloader class for handling the em dataset and the related labels.

    :param volpath: (string) path to the directory that contains the em volume(s).
    :param gtpath: (string) path to the directory that contains the groundtruth volume(s).
    :param volume:
    :param label:
    :param chunk_size: (tuple) defines the chunks in which the data is loaded. Can help to overcome Memory errors.
    :param mode: (string) Sets the mode in which the volume should be clustered (3d || 2d).
    :param ff: (string) defines the file format that you want to work with. (default: png)
    '''

    def __init__(self, cfg, volume=None, label=None, feature="shape"):
        self.cfg = cfg
        if volume is not None:
            print('em data loaded: ', self.volume.shape)
        else:
            self.volpath = self.cfg.DATASET.EM_PATH
            self.volume = volume

        if label is not None:
            print('gt data loaded: ', self.label.shape)
        else:
            self.gtpath = self.cfg.DATASET.LABEL_PATH
            self.label = label

        self.chunk_size = self.cfg.DATASET.CHUNK_SIZE
        self.ff = self.cfg.DATASET.FILE_FORMAT
        if self.cfg.SYSTEM.NUM_CPUS is None:
            self.cpus = multiprocessing.cpu_count()
        else:
            self.cpus = self.cfg.SYSTEM.NUM_CPUS

        self.region_limit = cfg.AUTOENCODER.REGION_LIMIT
        self.chunks_per_cpu = cfg.AUTOENCODER.CHUNKS_CPU
        self.upper_limit = cfg.AUTOENCODER.UPPER_BOUND
        self.lower_limit = cfg.AUTOENCODER.LOWER_BOUND
        self.target_size = cfg.AUTOENCODER.TARGET
        self.vae_feature = feature
        self.mito_volume_file_name = "datasets/vae/" + "vae_data_{}.h5".format(cfg.AUTOENCODER.TARGET[0])

    def __len__(self):
        '''
        Required by torch to return the length of the dataset.
        :returns: integer
        '''
        with h5py.File(self.mito_volume_file_name, 'r') as f:
            return len(f[self.vae_feature + "_volume"])

    def __getitem__(self, idx):
        '''
        Required by torch to return one item of the dataset.
        :param idx: index of the object
        :returns: object from the volume
        '''
        with h5py.File(self.mito_volume_file_name, 'r') as f:
            return f[self.vae_feature + "_volume"][idx]

    def load_chunk(self, vol='both', mode='3d'):
        '''
        Load chunk of em and groundtruth data for further processing.
        :param vol: (string) choose between -> 'both', 'em', 'gt' in order to specify
                     with volume you want to load.
        '''
        emfns = sorted(glob.glob(self.volpath + '*.' + self.ff))
        gtfns = sorted(glob.glob(self.gtpath + '*.' + self.ff))
        emdata = 0
        gt = 0

        if mode == '2d':
            if (vol == 'em') or (vol == 'both'):
                emdata = readvol(emfns[0])
                emdata = np.squeeze(emdata)
                print('em data loaded: ', emdata.shape)
            if (vol == 'gt') or (vol == 'both'):
                gt = readvol(gtfns[0])
                gt = np.squeeze(gt)
                print('gt data loaded: ', gt.shape)

        if mode == '3d':
            if (vol == 'em') or (vol == 'both'):
                if self.volume is None:
                    emdata = folder2Vol(self.volpath, self.chunk_size, file_format=self.ff)
                    print('em data loaded: ', emdata.shape)
            if (vol == 'gt') or (vol == 'both'):
                if self.label is None:
                    gt = folder2Vol(self.gtpath, self.chunk_size, file_format=self.ff)
                    print('gt data loaded: ', gt.shape)

        return (emdata, gt)

    def list_segments(self, vol, labels, min_size=2000, os=0, mode='3d'):
        '''
        This function creats a list of arrays that contain the unique segments.
        :param vol: (np.array) volume that contains the pure em data. (2d || 3d)
        :param label: (np.array) volume that contains the groundtruth. (2d || 3d)
        :param min_size: (int) this sets the minimum size of mitochondria region in order to be safed to the list. Used only in 2d.
        :param os: (int) defines the offset that should be used for cutting the bounding box. Be careful with offset as it can lead to additional regions in the chunks.
        :param mode: (string) 2d || 3d --> 2d gives you 2d arrays of each slice (same mitochondria are treated differently as they loose their touch after slicing)
                                       --> 3d gives you the whole mitochondria in a 3d volume.

        :returns: (dict) of (np.array) objects that contain the segments with labels as keys.
        '''
        bbox_dict = {}
        mask = np.zeros(shape=vol.shape, dtype=np.uint16)
        mask[labels > 0] = 1
        vol[mask == 0] = 0

        if mode == '2d':
            bbox_list = []
            for idx in range(vol.shape[0]):
                image = vol[idx, :, :]
                gt_img = labels[idx, :, :]
                label2d, num_label = label(gt_img, return_num=True)
                regions = regionprops(label2d, cache=False)

                for props in regions:
                    boundbox = props.bbox
                    if props.bbox_area > min_size:
                        if ((boundbox[0] - os) < 0) or ((boundbox[2] + os) > image.shape[0]) or (
                                (boundbox[1] - os) < 0) or ((boundbox[3] + os) > image.shape[1]):
                            tmparr = image[boundbox[0]:boundbox[2], boundbox[1]:boundbox[3]]
                        else:
                            tmparr = image[(boundbox[0] - os):(boundbox[2] + os), (boundbox[1] - os):(boundbox[3] + os)]
                        bbox_list.append(tmparr)

            bbox_dict = {i: bbox_list[i] for i in range(len(bbox_list))}

        elif mode == '3d':
            chunk_dict = {}

            label3d, num_label = label(labels, return_num=True)
            regions = regionprops(label3d, cache=False)

            for props in regions:
                boundbox = props.bbox
                if ((boundbox[1] - os) < 0) or ((boundbox[4] + os) > vol.shape[1]) or ((boundbox[2] - os) < 0) or (
                        (boundbox[5] + os) > vol.shape[2]):
                    tmparr = vol[boundbox[0]:boundbox[3], boundbox[1]:boundbox[4], boundbox[2]:boundbox[5]]
                else:
                    tmparr = vol[boundbox[0]:boundbox[3], (boundbox[1] - os):(boundbox[4] + os),
                             (boundbox[2] - os):(boundbox[5] + os)]
                bbox_dict[props.label] = tmparr
        else:
            raise ValueError('No valid dimensionality mode in function list_segments.')

        return (bbox_dict)

    def prep_data_info(self, volopt='gt', save=False):
        '''
        This function aims as an inbetween function iterating over the whole dataset in efficient
        and memory proof fashion in order to preserve information that is needed for further steps.
        :param volopt: (string) this sets the volume you want to use for the operation. default: gt
        :param kernel_n: (int) number of CPU kernels you want to use for multiprocessing.

        :returns added: (dict) that contains the labels with respective information as (list): [pixelsize, [slice_index(s)]]
        '''
        if volopt == 'gt':
            fns = sorted(glob.glob(self.gtpath + '*.' + self.ff))
        elif volopt == 'em':
            fns = sorted(glob.glob(self.volpath + '*.' + self.ff))
        else:
            raise ValueError('Please enter the volume on which \'prep_data_info\' should run on.')

        with multiprocessing.Pool(processes=self.cpus) as pool:
            result = pool.starmap(self.calc_props, enumerate(fns))

        added = {}
        for dicts in result:
            for key, value in dicts.items():
                if key in added:
                    added[key][0] += value[0]
                    added[key][1].append(value[1])
                else:
                    added.setdefault(key, [])
                    added[key].append(value[0])
                    added[key].append([value[1]])

        result_array = []
        for result in added.keys():
            result_array.append({
                'id': result,
                'size': added[result][0],
                'slices': added[result][1]
            })
        if save:
            with open(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.DATAINFO), 'w') as f:
                json.dump(result_array, f, cls=NumpyEncoder)
                f.close()

        return (result_array)

    def calc_props(self, idx, fns):
        '''
        Helper function for 'prep_data_info'
        :param idx: (int) this is the slice index that correspondes to the image slice. E.g. idx 100 belongs to image 100.
        :param fns: (string) list of filenames.
        :returns result: (dict) with each segment. key: idx of segment -- value: [number of pixels in segment, idx of slice].
        '''
        result = {}
        idx_list = []
        if os.path.exists(fns):
            tmp = imageio.imread(fns)
            labels, num_labels = np.unique(tmp, return_counts=True)

            for l in range(labels.shape[0]):
                if labels[l] == 0:
                    continue
                result.setdefault(labels[l], [])
                result[labels[l]].append(num_labels[l])
                result[labels[l]].append(idx)

        return result

    def precluster(self, mchn='simple', n_groups=5):
        '''
        Function preclusters the mitochondria into buckets of similar size in order to avoid
        sparsity and loss of information while extracting latent representation of the mitochondria.
        '''
        if os.path.exists(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.DATAINFO)) \
                and os.stat(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.DATAINFO)).st_size != 0:
            with open(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.DATAINFO), 'r') as f:
                data_info = json.loads(f.read())
        else:
            data_info = self.prep_data_info(save=True)

        tmp = np.stack(([mito['id'] for mito in data_info], [mito['size'] for mito in data_info]), axis=-1)

        if mchn == 'simple':
            sorted = tmp[tmp[:, 1].argsort()[::-1]]
            splitted = np.array_split(sorted, n_groups, axis=0)
            id_lists = [tmp[:, 0].tolist() for tmp in splitted]

        elif mchn == 'cluster':
            model = KMeans(n_clusters=n_groups)
            res_grps = model.fit_predict(np.array(tmp[:, 1]).reshape(-1, 1))
            id_lists = [[]] * n_groups
            for idx in range(len(res_grps)):
                id_lists[res_grps[idx]].append(tmp[:, 0][idx])
        else:
            raise ValueError(
                'Please enter the a valid mechanismn you want to group that mitochondria. \'simple\' or \'cluster\'.')

        return id_lists

    def extract_scale_mitos(self):
        '''
        Function to extract the objects as volumes and scale them. Then its saves the scaled volumes to an h5 file.
        '''
        if os.path.exists(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.DATAINFO)) \
                and os.stat(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.DATAINFO)).st_size != 0:
            with open(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.DATAINFO), 'r') as f:
                regions = json.loads(f.read())
        else:
            regions = self.prep_data_info(save=False)

        print("{} objects found in the ground truth".format(len(regions)))

        regions = pd.DataFrame(regions)
        regions = regions[(self.upper_limit > regions['size']) & (self.lower_limit < regions['size'])].values.tolist()
        filtered_length = len(regions)
        print("{} within limits {} and {}".format(filtered_length, self.lower_limit, self.upper_limit))
        if self.region_limit is not None:
            regions = regions[:self.region_limit]
            print("{} will be extracted due to set region_limit".format(self.region_limit))
        with h5py.File(self.mito_volume_file_name, "w") as f:
            f.create_dataset("shape_volume", (len(regions), 1, *self.target_size))
            f.create_dataset("texture_volume", (len(regions), 1, *self.target_size))
            f.create_dataset("id", (len(regions),))

            with multiprocessing.Pool(processes=self.cpus) as pool:
                for i in tqdm(range(0, len(regions), int(self.cpus * self.chunks_per_cpu))):
                    try:
                        results = pool.map(self.get_mito_volume, regions[i:i + int(self.cpus * self.chunks_per_cpu)])
                        for j, result in enumerate(results):
                            f["id"][i + j] = result[0]
                            f["shape_volume"][i + j] = result[1]
                            f["texture_volume"][i + j] = result[2]
                    except:
                        print("error in extraction, i: {}".format(i))
                        exit()

    def get_mito_volume(self, region):
        '''
        Preprocessing function to extract and scale the mitochondria as volume
        :param region: (dict) one region object provided by Dataloader.prep_data_info
        :returns result: (numpy.array) a numpy array with the target dimensions and the mitochondria in it
        '''
        gt_volume, em_volume = self.get_volumes_from_slices(region)

        mito_regions = regionprops(gt_volume, cache=False)
        if len(mito_regions) != 1:
            print("something went wrong during volume building. region count: {}".format(len(mito_regions)))

        mito_region = mito_regions[0]

        shape = gt_volume[mito_region.bbox[0]:mito_region.bbox[3] + 1,
                mito_region.bbox[1]:mito_region.bbox[4] + 1,
                mito_region.bbox[2]:mito_region.bbox[5] + 1].astype(np.float32)

        texture = em_volume[mito_region.bbox[0]:mito_region.bbox[3] + 1,
                  mito_region.bbox[1]:mito_region.bbox[4] + 1,
                  mito_region.bbox[2]:mito_region.bbox[5] + 1].astype(np.float32)

        scaled_shape = resize(shape, self.target_size, order=0, anti_aliasing=False)
        scaled_shape = scaled_shape / scaled_shape.max()
        scaled_shape = np.expand_dims(scaled_shape, 0)

        scaled_texture = resize(texture, self.target_size, order=0, anti_aliasing=False)
        scaled_texture = scaled_texture / scaled_texture.max()
        scaled_texture = np.expand_dims(scaled_texture, 0)

        return [region[0], scaled_shape, scaled_texture]

    def get_volumes_from_slices(self, region):
        '''
        #TODO
        :param region:
        :returns gt_volume, em_volume:
        '''
        gt_all_fn = sorted(glob.glob(self.gtpath + '*.' + self.ff))
        em_all_fn = sorted(glob.glob(self.volpath + '*.' + self.ff))

        gt_fns = [gt_all_fn[id] for id in region[2]]
        em_fns = [em_all_fn[id] for id in region[2]]

        gt_volume = imageio.imread(gt_fns[0])
        em_volume = imageio.imread(em_fns[0])

        gt_volume[gt_volume != region[0]] = 0
        em_volume[gt_volume != region[0]] = 0

        for i in range(len(gt_fns) - 1):
            gt_slice = imageio.imread(gt_fns[i])
            em_slice = imageio.imread(em_fns[i])

            gt_slice[gt_slice != region[0]] = 0
            em_slice[gt_slice != region[0]] = 0

            gt_volume = np.dstack((gt_volume, gt_slice))
            em_volume = np.dstack((em_volume, em_slice))

        gt_volume = np.moveaxis(gt_volume, -1, 0)
        em_volume = np.moveaxis(em_volume, -1, 0)

        return gt_volume, em_volume
