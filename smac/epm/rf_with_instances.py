import numpy as np
import logging

import pyrfr.regression

from smac.epm.base_epm import AbstractEPM


__author__ = "Aaron Klein, Marius Lindauer, Matthias Feurer"
__copyright__ = "Copyright 2015, ML4AAD"
__license__ = "3-clause BSD"
__maintainer__ = "Aaron Klein"
__email__ = "kleinaa@cs.uni-freiburg.de"
__version__ = "0.0.1"


class RandomForestWithInstances(AbstractEPM):

    '''
    Interface to the random forest that takes instance features
    into account.

    Parameters
    ----------
    types: np.ndarray (D)
        Specifies the number of categorical values of an input dimension. Where
        the i-th entry corresponds to the i-th input dimension. Let say we have
        2 dimension where the first dimension consists of 3 different
        categorical choices and the second dimension is continuous than we
        have to pass np.array([2, 0]). Note that we count starting from 0.
    n_insts: int
        number of instances
    instance_features: np.ndarray (I, K)
        Contains the K dimensional instance features
        of the I different instances
    num_trees: int
        The number of trees in the random forest.
    do_bootstrapping: bool
        Turns on / off bootstrapping in the random forest.
    ratio_features: float
        The ratio of features that are considered for splitting.
    min_samples_split: int
        The minimum number of data points to perform a split.
    min_samples_leaf: int
        The minimum number of data points in a leaf.
    max_depth: int

    eps_purity: float

    max_num_nodes: int

    seed: int
        The seed that is passed to the random_forest_run library.
    '''

    def __init__(self, types,
                 instance_features=None,
                 num_trees=10,
                 do_bootstrapping=True,
                 n_points_per_tree=0,
                 ratio_features=5. / 6.,
                 min_samples_split=3,
                 min_samples_leaf=3,
                 max_depth=20,
                 eps_purity=1e-8,
                 max_num_nodes=1000,
                 seed=42):

        if instance_features is not None:
            self.instance_features = instance_features
            self.types = types
        else:
            # dummy instance features
            self.instance_features = np.zeros((1, 1))
            self.types = np.hstack((types, np.zeros((1), dtype=np.uint)))

        self.rf = pyrfr.regression.binary_rss()
        self.rf.num_trees = num_trees
        self.rf.seed = seed
        self.rf.do_bootstrapping = do_bootstrapping
        self.rf.num_data_points_per_tree = n_points_per_tree
        max_features = 0 if ratio_features >= 1.0 else \
            max(1, int(types.shape[0] * ratio_features))
        self.rf.max_features = max_features
        self.rf.min_samples_to_split = min_samples_split
        self.rf.min_samples_in_leaf = min_samples_leaf
        self.rf.max_depth = max_depth
        self.rf.epsilon_purity = eps_purity
        self.rf.max_num_nodes = max_num_nodes

        # This list well be read out by save_iteration() in the solver
        self.hypers = [num_trees, max_num_nodes, do_bootstrapping,
                       n_points_per_tree, ratio_features, min_samples_split,
                       min_samples_leaf, max_depth, eps_purity, seed]
        self.seed = seed

        self.logger = logging.getLogger("RF")

        # Never use a lower variance than this
        self.var_threshold = 10 ** -5

    def train(self, configs, f_map, y, **kwargs):
        """Trains the random forest on X and y.

        Parameters
        ----------
        configs : np.ndarray [n_configs, n_params]
            Input data points.
        f_map: np.darray [n_samples, 2]
            Mapping configs to instance features
        Y : np.ndarray [n_samples, ]
            The corresponding target values.

        Returns
        -------
        self
        """

        y = y.flatten()

        data = pyrfr.regression.mostly_continuous_data_with_instances_container(
            configs.shape[1], self.instance_features.shape[1])
        data.import_configurations(configs)
        data.import_instances(self.instance_features)
        data.add_data_points(f_map, y)
        # needs to be stored for the marginalized predictions
        self.data = data

        self.rf.fit(data)
        return self

    def predict(self, X):
        """Predict means and variances for given X.
        If the RF got no instance features,
        an hallucinated 0 was appended to each sample.
        Needs also to be done here.

        Parameters
        ----------
        X : np.ndarray of shape = [n_samples, n_features (config + instance
        features)]

        Returns
        -------
        means : np.ndarray of shape = [n_samples, 1]
            Predictive mean
        vars : np.ndarray  of shape = [n_samples, 1]
            Predictive variance
        """
        if len(X.shape) != 2:
            raise ValueError(
                'Expected 2d array, got %dd array!' % len(X.shape))
        if X.shape[1] != self.types.shape[0]:
            raise ValueError('Rows in X should have %d entries but have %d!' %
                             (self.types.shape[0], X.shape[1]))

        means, vars = self.rf.batch_predictions(X)
        
        return means.reshape((-1, 1)), vars.reshape((-1, 1))

    def predict_marginalized_over_instances(self, X):
        """Predict mean and variance marginalized over all instances.

        Returns the predictive mean and variance marginalised over all
        instances for a set of configurations.

        Parameters
        ----------
        X : np.ndarray of shape = [n_features (config), ]

        Returns
        -------
        means : np.ndarray of shape = [n_samples, 1]
            Predictive mean
        vars : np.ndarray  of shape = [n_samples, 1]
            Predictive variance
        """

        if self.instance_features is None or \
                len(self.instance_features) == 0:
            mean, var = self.predict(X)
            var[var < self.var_threshold] = self.var_threshold
            var[np.isnan(var)] = self.var_threshold
            return mean, var
        else:
            n_instance_features = self.instance_features.shape[1]

        if len(X.shape) != 2:
            raise ValueError(
                'Expected 2d array, got %dd array!' % len(X.shape))

        if X.shape[1] != self.types.shape[0] - n_instance_features:
            raise ValueError('Rows in X should have %d entries but have %d!' %
                             (self.types.shape[0] - n_instance_features,
                              X.shape[1]))

        mean = np.zeros(X.shape[0])
        var = np.zeros(X.shape[0])
        for i, x in enumerate(X):

            x_ = np.hstack((x, np.zeros((self.instance_features.shape[1]))))
            mean_x, var_x = self.rf.predict_marginalized_over_instances(
                x_, self.data)

            if var_x < self.var_threshold:
                var_x = self.var_threshold

            var[i] = var_x
            mean[i] = mean_x

        var[var < self.var_threshold] = self.var_threshold
        var[np.isnan(var)] = self.var_threshold

        if len(mean.shape) == 1:
            mean = mean.reshape((-1, 1))
        if len(var.shape) == 1:
            var = var.reshape((-1, 1))

        return mean, var
