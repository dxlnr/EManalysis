import glob
import os, sys
import numpy as np
import multiprocessing
import functools
import imageio
import h5py
from scipy.sparse import bsr_matrix, coo_matrix, csr_matrix
from skimage.color import label2rgb
from tqdm import tqdm

from analyzer.data.utils.data_raw import save_m_to_image

def convert_to_sparse(inputs):
    '''
    Convert any sort of input (list of different sized arrays) to a sparse matrix
    as preprocessing step in order to cluster later. Sparse has added 0 in every feature vector.
    :param input: (list) or (dict) of feature vectors that differ in shape.

    :returns sparse: (M, N) matrix. Rows represent segment respectively to the res_labels (one full feature vector).
                                    columns represent the individual features.
    '''
    if type(inputs) is dict:
        in_list = list(inputs.values())
    elif type(inputs) is list:
        in_list = inputs
    else:
        raise ValueError('Input type is not supported for \'convert_to_sparse\' function.')

    in_list = list(inputs.values())
    row = len(inputs)
    column = int(max(arr.shape[0] for arr in in_list if arr.size != 0))

    sparse = np.zeros(shape=(row, column), dtype=np.float64)
    for idx in range(len(in_list)):
        tmp = in_list[idx]
        if in_list[idx].shape[0] < column:
            tmp = np.append(in_list[idx], np.zeros((column - in_list[idx].shape[0], )), axis=0)
        sparse[idx] = tmp

    return (sparse)

def recompute_from_res(labels, result, vol= None, volfns=None, dprc='full', fp='', mode='3d', neuroglancer=False, em_path=None):
    '''
    Take the result labels from clustering algorithm and adjust the old labels. NOTE: '3d' mode is way faster.
    :param labels: (np.array) vector that contains old labels that you want to adjust.
    :param result: (np.array) vector that contains the new labels.
    :param vol: (np.array) matrix that is the groundtruth mask.
    :param volfns: (list) of image filenames that contain the groundtruth mask.
    :param fp: (string) this should give you the folder path where the resulting image should be stored.
    :param dprc: (string)
    :returns cld_labels: (np.array) vol matrix that is the same shape as vol mask. But with adjusted labels.
    '''
    print('\nStarting to relabel the mask with the results from the clustering results.')
    if dprc == 'full':
        if mode == '2d':
            cld_labels = np.zeros(shape=labels.shape)

            for r in range(labels.shape[0]):
                tmp = labels[r]
                for idx in range(np.amin(tmp[np.nonzero(tmp)]), np.amax(tmp) + 1):
                    tmp[tmp == idx] = result[idx - 1] + 1 # + 1 in order to secure that label 0 is not missed.

                cld_labels[r] = tmp
        else:
            ldict = {}
            for k, v in zip(labels, result):
                ldict[k] = v + 1  # + 1 in order to secure that label 0 is not missed.

            k = np.array(list(ldict.keys()))
            v = np.array(list(ldict.values()))

            mapv = np.zeros(k.max() + 1)
            mapv[k] = v
            cld_labels = mapv[vol]
    elif dprc == 'iter':
        ldict = {}
        for k, v in zip(labels, result):
            ldict[k] = v + 1  # + 1 in order to secure that label 0 is not missed.

        k = np.array(list(ldict.keys()))
        v = np.array(list(ldict.values()))

        if neuroglancer:
            emfns = glob.glob(em_path+"*.png")
            recompute_from_res_per_slice_h5(volfns, emfns, k=k, v=v, fp=fp)
        else:
            with multiprocessing.Pool(processes=multiprocessing.cpu_count()) as pool:
                pool.starmap(functools.partial(recompute_from_res_per_slice, k=k, v=v, fp=fp), enumerate(volfns))
        cld_labels = 0 #Just to avoid error message.
    else:
        raise ValueError('No valid data processing option choosen. Please choose \'full\' or \'iter\'.')
    print('Relabeling of the mask is done.\n')
    return cld_labels

def recompute_from_res_per_slice(idx, fns, k, v, fp):
    '''
    Helper function to iterate over the whole dataset in order to replace the labels with its
    clustering labels.
    '''
    if idx % 50 == 0:
        print('relabeling of image {} done.'.format(idx))
    if os.path.exists(fns):
        vol = imageio.imread(fns)
        mapv = np.zeros(k.max() + 1)
        mapv[k] = v
        cld_labels = mapv[vol]
    else:
        raise ValueError('image {} not found.'.format(fns))
    save_m_to_image(cld_labels, 'cluster_mask', fp=fp, idx=idx, ff='png')

def correct_idx_feat(base_labels, labels, features):
    '''
    This function should check and if necessary correct the labeling order and their
    corresponding features to not mix up different features for the clustering.
    :param base_labels: (np.array) This is the reference labels order.
    :param labels: (np.array) labels that do not fit the base_labels.
    :param features: features that should be aligned according to the base_labels.
    :returns : ordered features.
    '''
    ordered_feat = np.array(shape=features.shape)
    for i in range(base_labels.shape[0]):
        feat_idx = np.where(labels == base_labels[i])
        ordered_feat[i] = features[feat_idx]

    return ordered_feat

def check_feature_order(base_labels, labels):
    '''checking the label order of the features, to secure that the order is correct
    an the features are not mixed up for the clustering. Very important!'''
    return (base_labels == labels).all()

def convert_dict_mtx(inputs, valn):
    '''
    This function converts a dict with labels as keys and values to 2 separate matrices that represent
    feature vectors/matrix and labels vector.
    :param input: (dict) or (list)
    :param valn: (string) name of value parameter in dict.
    :returns labels: (np.array) same shape as volume with all the labels.
    :returns values: (np.array) is a vetor that contains the corresponding values for every label.
    '''
    if (type(inputs) is list):
        labels = np.array([seg['id'] for seg in inputs])
        if isinstance(inputs[0][valn], (list, tuple, np.ndarray)) is False:
            values = np.array([seg[valn] for seg in inputs])
        else:
            values = np.concatenate([seg[valn] for seg in inputs])
    elif (type(inputs) is dict):
        labels, values = zip(* inputs.items())
        labels = np.array(labels, dtype=np.uint16)
        values = np.array(values, dtype=np.uint16)
    else:
        raise TypeError('input type {} can not be processed.'.format(type(inputs)))

    return (labels, values)

def min_max_scale(X, desired_range=(0,1)):
    '''
    Transform features by scaling each feature to a given range.
    :param X: Matrix you want to transform.
    :param range: Desired range of transformed data.
    :returns X_scaled: scaled matrix.
    '''
    min_v = desired_range[0]
    max_v = desired_range[1]
    X_std = (X - X.min()) / (X.max() - X.min())
    X_scaled = X_std * (max_v - min_v) + min_v
    return X_scaled

def recompute_from_res_per_slice_h5(volfns, emfns, k, v, fp, limit=100):
    '''
    Helper function to iterate over the whole dataset in order to replace the labels with its
    clustering labels and save them in h5 files.
    '''
    with h5py.File(fp+'neuroglancer.h5', 'w') as f:
        if limit is not None:
            volfns = volfns[:limit]
        vol = imageio.imread(volfns[0])
        ds = f.create_dataset('label', shape=(len(volfns), *vol.shape))
        ds2 = f.create_dataset('image', shape=(len(volfns), *vol.shape))
        for idx, fns in tqdm(enumerate(volfns), total=len(volfns)):
            if os.path.exists(fns):
                vol = imageio.imread(fns)
                em = imageio.imread(emfns[idx])
                mapv = np.zeros(k.max() + 1)
                mapv[k] = v
                cld_labels = mapv[vol]
            else:
                raise ValueError('image {} not found.'.format(fns))

            ds[idx] = cld_labels.astype(np.uint16)
            ds2[idx] = em/em.max()


def average_feature_h5(input_h5, output_h5, h5_name, label_length, feat_length):
    '''averaging features that were cut by sliding window appproach.'''
    with h5py.File(output_h5, 'w') as h5f:
        h5f.create_dataset(name=h5_name, shape=(label_length, feat_length))
        h5f.create_dataset(name='id', shape=(label_length,))

        with h5py.File(input_h5, 'r') as f:
            id_vec = np.array(f['id'], dtype=np.int32)
            feats = np.array(f[h5_name])
            uniq = np.unique(np.array(f['id'], dtype=np.int32))

            for i, label in enumerate(list(uniq)):
                idx_vec = np.where(id_vec == label)
                average_vec = np.zeros(shape=(feats[0].shape))
                for idx in idx_vec[0]:
                    average_vec += feats[idx]

                feat_vec = average_vec / idx_vec[0].shape[0]

                h5f[h5_name][i] = feat_vec
                h5f['id'][i] = label

                if i % 1000 == 0:
                    print('[{}]/[{}] '.format(i, len(list(uniq))))
