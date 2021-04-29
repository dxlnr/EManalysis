import os, sys
import numpy as np
import json
import glob
import multiprocessing
import functools
from numpyencoder import NumpyEncoder
import imageio

from sklearn.metrics import normalized_mutual_info_score, pair_confusion_matrix
from tqdm import tqdm

from analyzer.model.utils.extracting import calc_props

class Evaluationmodel():
	'''
	Setups up the model for evaluation purposes after the clustering is finished
	and a groundtruth is there. You might also just decide to not use it in order to
	keep it unsupervised.
	:param cfg: configuration manager.
	:param dl: Dataloader
	:param rsl_vector: This is the resulting vector extracted from the clustering model.
					   (n,) (np.array) with n beeing the number of samples.
	'''
	def __init__(self, cfg, dl):
		self.cfg = cfg
		self.dl = dl
		#self.rsl_vector = rsl_vector

	def eval(self, rsl_vector):
		'''
		Evaluation of the clustering by comparing the gt to the results.
		'''
		rsl_values, rsl_counts = np.unique(rsl_vector, return_counts=True)
		gt_values, gt_counts = np.unique(self.get_gt_vector(), return_counts=True)
		print('\nThe following shows how many datapoints each cluster consists of.')
		print('result distribution vector {}'.format(rsl_counts))
		print('ground truth distribution vector {}'.format(gt_counts))

		# MUTUAL INFORMATION SCORE
		score = normalized_mutual_info_score(self.get_gt_vector(), rsl_vector)
		print(score)

	def get_gt_vector(self, fn='gt_vector.json', fast=False):
		if fast:
			return self.fast_create_gt_vector(fn)
		return self.create_gt_vector()

	def eval_volume(self, rsl_vector):
		'''
		Compute accuracy by comparing each segment from the result to the ground truth.
		'''
		if os.path.exists(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.ROOTF, 'eval_data_info.json')) \
				and os.stat(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.ROOTF, 'eval_data_info.json')).st_size != 0:
			with open(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.ROOTF, 'eval_data_info.json'), 'r') as f:
				data_info = json.loads(f.read())
		else:
			print('data info not found. Will be computed.')
			data_info = self.prep_data_info(save=True)

		# Preparation section.
		gt_fns = sorted(glob.glob(self.dl.gtpath + '*.' + self.cfg.DATASET.FILE_FORMAT))
		rsl_fns = sorted(glob.glob(self.cfg.CLUSTER.OUTPUTPATH + '*.' + self.cfg.DATASET.FILE_FORMAT))
		if not rsl_fns or not gt_fns:
			raise ValueError('Please make sure that ground truth and result images are there and the path is correct.')

		rsl_values, rsl_counts = np.unique(rsl_vector, return_counts=True)
		gt_values, gt_counts = np.unique(self.get_gt_vector(), return_counts=True)

		s_gt = np.array([gt_values for _, gt_values in sorted(zip(gt_counts, gt_values))])
		s_rsl = np.array([rsl_values for _, rsl_values in sorted(zip(rsl_counts, rsl_values))])

		correct = 0
		for key, value in data_info.items():
			slices = value[0]
			randompts = value[2]

			gt = imageio.imread(gt_fns[slices[0]])
			rsl = imageio.imread(rsl_fns[slices[0]])

			gt_label_index = np.where(s_gt == gt[randompts[0][0], randompts[0][1]])[0].item()
			rsl_label_index = np.where(s_rsl == rsl[randompts[0][0], randompts[0][1]])[0].item()
			if gt_label_index == rsl_label_index:
				correct = correct + 1

		accuracy = correct / np.sum(gt_counts)
		print('\nfound accuracy: ', accuracy)

	def create_gt_vector(self, fn='gt_vector.json', save=True):
		'''
		This function should create a resulting label vector that is the ground truth.
		:returns (n,) vector. n is the number of samples/segments.
		'''
		if os.path.exists(os.path.join(self.cfg.DATASET.ROOTF, fn)) \
				and os.stat(os.path.join(self.cfg.DATASET.ROOTF, fn)).st_size != 0:
			with open(os.path.join(self.cfg.DATASET.ROOTF, fn), 'r') as f:
				gt_vector = json.loads(f.read())
		else:
			print('gt vector not found. Will be computed.')
			if os.path.exists(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.ROOTF, 'eval_data_info.json')) \
					and os.stat(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.ROOTF, 'eval_data_info.json')).st_size != 0:
				with open(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.ROOTF, 'eval_data_info.json'), 'r') as f:
					data_info = json.loads(f.read())
			else:
				print('data info not found. Will be computed.')
				data_info = self.prep_data_info(save=True)

			fns = sorted(glob.glob(self.dl.gtpath + '*.' + self.cfg.DATASET.FILE_FORMAT))
			gt_ids = list(map(int, data_info.keys()))
			gt_vector = np.zeros(len(gt_ids), dtype=np.uint16)
			for key, value in data_info.items():
				slices = value[0]
				centerpoints = value[1]
				randompts = value[2]
				for i, s in enumerate(slices):
					gt = imageio.imread(fns[s])
					if gt[centerpoints[i][0], centerpoints[i][1]] == 0 and gt[randompts[i][0], randompts[i][1]] == 0:
						continue
					else:
						if gt[centerpoints[i][0], centerpoints[i][1]] != 0:
							gt_vector[gt_ids.index(int(key))] = gt[centerpoints[i][0], centerpoints[i][1]]
						else:
							gt_vector[gt_ids.index(int(key))] = gt[randompts[i][0], randompts[i][1]]
						break

				if gt_ids.index(int(key)) % 1000 == 0:
					print('altered [{}/{}] labels for ground truth vector.'.format(gt_ids.index(int(key)), len(gt_ids)))
			if save:
				with open(os.path.join(self.cfg.DATASET.ROOTF, 'gt_vector.json'), 'w') as f:
					json.dump(gt_vector, f, cls=NumpyEncoder)
					f.close()

		values, counts = np.unique(gt_vector, return_counts=True)

		if (values == 0).any():
			print('gt vector contains 0 as label.')
			print('values: ', values)
			print('counts: ', counts)

		return gt_vector

	def prep_data_info(self, save=False):
		'''
		Extracting the label and its centerpoints.
		'''
		fns = sorted(glob.glob(self.dl.labelpath + '*.' + self.cfg.DATASET.FILE_FORMAT))

		with multiprocessing.Pool(processes=multiprocessing.cpu_count()) as pool:
			tmp = pool.starmap(functools.partial(calc_props, prop_list=['slices', 'centroid', 'random_pt']), enumerate(fns))

		result_dict = {}
		for dicts in tmp:
			for key, value in dicts.items():
				if key in result_dict:
					result_dict[key][0].append(value[0])
					result_dict[key][1].append(value[1])
					result_dict[key][2].append(value[2])
				else:
					result_dict.setdefault(key, [])
					result_dict[key].append([value[0]])
					result_dict[key].append([value[1]])
					result_dict[key].append([value[2]])

		if save:
			with open(os.path.join(self.cfg.SYSTEM.ROOT_DIR, self.cfg.DATASET.ROOTF, 'eval_data_info.json'), 'w') as f:
				json.dump(result_dict, f, cls=NumpyEncoder)
				f.close()
		return result_dict

	def fast_create_gt_vector(self, fn='gt_vector.json', save=True):
		if os.path.exists(os.path.join(self.cfg.DATASET.ROOTF, fn)) \
				and os.stat(os.path.join(self.cfg.DATASET.ROOTF, fn)).st_size != 0:
			with open(os.path.join(self.cfg.DATASET.ROOTF, fn), 'r') as f:
				gt_vector = json.loads(f.read())
		else:
			print('gt vector not found. Will be computed.')
			gt_images = glob.glob(self.dl.gtpath + '/*.png')
			label_images = glob.glob(self.dl.labelpath + '/*.png')

			if len(gt_images) != len(label_images):
				print("gt images dont match label images")
				exit()
			gt_vector = {}

			for i, label_image in tqdm(enumerate(label_images), total=len(label_images)):
				label_image = imageio.imread(label_image)
				gt_image = imageio.imread(gt_images[i])
				labels = np.unique(label_image)

				for label in labels:
					if label == 0 or label in gt_vector.keys():
						continue

					coords = np.argwhere(label_image==label)[0]
					gt_vector[label] = gt_image[coords[0], coords[1]]
			gt_vector = [value for key, value in sorted(gt_vector.items())]
			if save:
				with open(os.path.join(self.cfg.DATASET.ROOTF, 'gt_vector.json'), 'w') as f:
					json.dump(gt_vector, f, cls=NumpyEncoder)
					f.close()

		values, counts = np.unique(gt_vector, return_counts=True)
		if (values == 0).any():
			print('gt vector contains 0 as label.')
			print('values: ', values)
			print('counts: ', counts)

		return gt_vector