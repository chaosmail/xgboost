# coding: utf-8
# pylint: disable=too-many-arguments, too-many-locals, invalid-name, fixme
"""Scikit-Learn Wrapper interface for XGBoost."""
from __future__ import absolute_import

import numpy as np
from .core import Booster, DMatrix, XGBoostError
from .training import train

from .compat import (SKLEARN_INSTALLED, XGBModelBase,
                     XGBClassifierBase, XGBRegressorBase, LabelEncoder)


def _objective_decorator(func):
    """Decorate an objective function

    Converts an objective function using the typical sklearn metrics
    signature so that it is usable with ``xgboost.training.train``

    Parameters
    ----------
    func: callable
        Expects a callable with signature ``func(y_true, y_pred)``:

        y_true: array_like of shape [n_samples]
            The target values
        y_pred: array_like of shape [n_samples]
            The predicted values

    Returns
    -------
    new_func: callable
        The new objective function as expected by ``xgboost.training.train``.
        The signature is ``new_func(preds, dmatrix)``:

        preds: array_like, shape [n_samples]
            The predicted values
        dmatrix: ``DMatrix``
            The training set from which the labels will be extracted using
            ``dmatrix.get_label()``
    """
    def inner(preds, dmatrix):
        labels = dmatrix.get_label()
        return func(labels, preds)
    return inner


class XGBModel(XGBModelBase):
    # pylint: disable=too-many-arguments, too-many-instance-attributes, invalid-name
    """Implementation of the Scikit-Learn API for XGBoost.

    Parameters
    ----------
    max_depth : int
        Maximum tree depth for base learners.
    learning_rate : float
        Boosting learning rate (xgb's "eta")
    n_estimators : int
        Number of boosted trees to fit.
    silent : boolean
        Whether to print messages while running boosting.
    objective : string or callable
        Specify the learning task and the corresponding learning objective or
        a custom objective function to be used (see note below).
    nthread : int
        Number of parallel threads used to run xgboost.
    gamma : float
        Minimum loss reduction required to make a further partition on a leaf node of the tree.
    min_child_weight : int
        Minimum sum of instance weight(hessian) needed in a child.
    max_delta_step : int
        Maximum delta step we allow each tree's weight estimation to be.
    subsample : float
        Subsample ratio of the training instance.
    colsample_bytree : float
        Subsample ratio of columns when constructing each tree.
    colsample_bylevel : float
        Subsample ratio of columns for each split, in each level.
    reg_alpha : float (xgb's alpha)
        L2 regularization term on weights
    reg_lambda : float (xgb's lambda)
        L1 regularization term on weights
    scale_pos_weight : float
        Balancing of positive and negative weights.

    base_score:
        The initial prediction score of all instances, global bias.
    seed : int
        Random number seed.
    missing : float, optional
        Value in the data which needs to be present as a missing value. If
        None, defaults to np.nan.

    Note
    ----
    A custom objective function can be provided for the ``objective``
    parameter. In this case, it should have the signature
    ``objective(y_true, y_pred) -> grad, hess``:

    y_true: array_like of shape [n_samples]
        The target values
    y_pred: array_like of shape [n_samples]
        The predicted values

    grad: array_like of shape [n_samples]
        The value of the gradient for each sample point.
    hess: array_like of shape [n_samples]
        The value of the second derivative for each sample point
    """
    def __init__(self, max_depth=3, learning_rate=0.1, n_estimators=100,
                 silent=True, objective="reg:linear",
                 nthread=-1, gamma=0, min_child_weight=1, max_delta_step=0,
                 subsample=1, colsample_bytree=1, colsample_bylevel=1,
                 reg_alpha=0, reg_lambda=1, scale_pos_weight=1,
                 base_score=0.5, seed=0, missing=None):
        if not SKLEARN_INSTALLED:
            raise XGBoostError('sklearn needs to be installed in order to use this module')
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.n_estimators = n_estimators
        self.silent = silent
        self.objective = objective

        self.nthread = nthread
        self.gamma = gamma
        self.min_child_weight = min_child_weight
        self.max_delta_step = max_delta_step
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.colsample_bylevel = colsample_bylevel
        self.reg_alpha = reg_alpha
        self.reg_lambda = reg_lambda
        self.scale_pos_weight = scale_pos_weight

        self.base_score = base_score
        self.seed = seed
        self.missing = missing if missing is not None else np.nan
        self._Booster = None

    def __setstate__(self, state):
        # backward compatiblity code
        # load booster from raw if it is raw
        # the booster now support pickle
        bst = state["_Booster"]
        if bst is not None and not isinstance(bst, Booster):
            state["_Booster"] = Booster(model_file=bst)
        self.__dict__.update(state)

    def booster(self):
        """Get the underlying xgboost Booster of this model.

        This will raise an exception when fit was not called

        Returns
        -------
        booster : a xgboost booster of underlying model
        """
        if self._Booster is None:
            raise XGBoostError('need to call fit beforehand')
        return self._Booster

    def get_params(self, deep=False):
        """Get parameter.s"""
        params = super(XGBModel, self).get_params(deep=deep)
        if params['missing'] is np.nan:
            params['missing'] = None  # sklearn doesn't handle nan. see #4725
        if not params.get('eval_metric', True):
            del params['eval_metric']  # don't give as None param to Booster
        return params

    def get_xgb_params(self):
        """Get xgboost type parameters."""
        xgb_params = self.get_params()

        xgb_params['silent'] = 1 if self.silent else 0

        if self.nthread <= 0:
            xgb_params.pop('nthread', None)
        return xgb_params

    def fit(self, X, y, eval_set=None, eval_metric=None,
            early_stopping_rounds=None, learning_rates=None, verbose=True):
        # pylint: disable=missing-docstring,invalid-name,attribute-defined-outside-init, redefined-variable-type
        """
        Fit the gradient boosting model

        Parameters
        ----------
        X : array_like
            Feature matrix
        y : array_like
            Labels
        eval_set : list, optional
            A list of (X, y) tuple pairs to use as a validation set for
            early-stopping
        eval_metric : str, callable, optional
            If a str, should be a built-in evaluation metric to use. See
            doc/parameter.md. If callable, a custom evaluation metric. The call
            signature is func(y_predicted, y_true) where y_true will be a
            DMatrix object such that you may need to call the get_label
            method. It must return a str, value pair where the str is a name
            for the evaluation and value is the value of the evaluation
            function. This objective is always minimized.
        early_stopping_rounds : int
            Activates early stopping. Validation error needs to decrease at
            least every <early_stopping_rounds> round(s) to continue training.
            Requires at least one item in evals.  If there's more than one,
            will use the last. Returns the model from the last iteration
            (not the best one). If early stopping occurs, the model will
            have three additional fields: bst.best_score, bst.best_iteration
            and bst.best_ntree_limit.
            (Use bst.best_ntree_limit to get the correct value if num_parallel_tree
            and/or num_class appears in the parameters)
        learning_rates: list or function
            List of learning rate for each boosting round
            or a customized function that calculates eta in terms of
            current number of round and the total number of boosting round (e.g. yields
            learning rate decay)
            - list l: eta = l[boosting round]
            - function f: eta = f(boosting round, num_boost_round)
        verbose : bool
            If `verbose` and an evaluation set is used, writes the evaluation
            metric measured on the validation set to stderr.
        """
        trainDmatrix = DMatrix(X, label=y, missing=self.missing)

        evals_result = {}
        if eval_set is not None:
            evals = list(DMatrix(x[0], label=x[1]) for x in eval_set)
            evals = list(zip(evals, ["validation_{}".format(i) for i in
                                     range(len(evals))]))
        else:
            evals = ()

        params = self.get_xgb_params()

        if callable(self.objective):
            obj = _objective_decorator(self.objective)
            params["objective"] = "reg:linear"
        else:
            obj = None

        feval = eval_metric if callable(eval_metric) else None
        if eval_metric is not None:
            if callable(eval_metric):
                eval_metric = None
            else:
                params.update({'eval_metric': eval_metric})

        self._Booster = train(params, trainDmatrix, self.n_estimators,
                              evals=evals, learning_rates=learning_rates,
                              early_stopping_rounds=early_stopping_rounds,
                              evals_result=evals_result, obj=obj, feval=feval,
                              verbose_eval=verbose)

        if evals_result:
            for val in evals_result.items():
                evals_result_key = list(val[1].keys())[0]
                evals_result[val[0]][evals_result_key] = val[1][evals_result_key]
            self.evals_result_ = evals_result

        if early_stopping_rounds is not None:
            self.best_score = self._Booster.best_score
            self.best_iteration = self._Booster.best_iteration
            self.best_ntree_limit = self._Booster.best_ntree_limit
        return self

    def predict(self, data, output_margin=False, ntree_limit=0):
        # pylint: disable=missing-docstring,invalid-name
        test_dmatrix = DMatrix(data, missing=self.missing)
        return self.booster().predict(test_dmatrix,
                                      output_margin=output_margin,
                                      ntree_limit=ntree_limit)

    def evals_result(self):
        """Return the evaluation results.

        If eval_set is passed to the `fit` function, you can call evals_result() to
        get evaluation results for all passed eval_sets. When eval_metric is also
        passed to the `fit` function, the evals_result will contain the eval_metrics
        passed to the `fit` function

        Returns
        -------
        evals_result : dictionary

        Example
        -------
        param_dist = {'objective':'binary:logistic', 'n_estimators':2}

        clf = xgb.XGBModel(**param_dist)

        clf.fit(X_train, y_train,
                eval_set=[(X_train, y_train), (X_test, y_test)],
                eval_metric='logloss',
                verbose=True)

        evals_result = clf.evals_result()

        The variable evals_result will contain:
        {'validation_0': {'logloss': ['0.604835', '0.531479']},
         'validation_1': {'logloss': ['0.41965', '0.17686']}}
        """
        if self.evals_result_:
            evals_result = self.evals_result_
        else:
            raise XGBoostError('No results.')

        return evals_result


class XGBClassifier(XGBModel, XGBClassifierBase):
    # pylint: disable=missing-docstring,too-many-arguments,invalid-name
    __doc__ = """Implementation of the scikit-learn API for XGBoost classification.

    """ + '\n'.join(XGBModel.__doc__.split('\n')[2:])

    def __init__(self, max_depth=3, learning_rate=0.1,
                 n_estimators=100, silent=True,
                 objective="binary:logistic",
                 nthread=-1, gamma=0, min_child_weight=1,
                 max_delta_step=0, subsample=1, colsample_bytree=1, colsample_bylevel=1,
                 reg_alpha=0, reg_lambda=1, scale_pos_weight=1,
                 base_score=0.5, seed=0, missing=None):
        super(XGBClassifier, self).__init__(max_depth, learning_rate,
                                            n_estimators, silent, objective,
                                            nthread, gamma, min_child_weight,
                                            max_delta_step, subsample,
                                            colsample_bytree, colsample_bylevel,
                                            reg_alpha, reg_lambda,
                                            scale_pos_weight, base_score, seed, missing)

    def fit(self, X, y, sample_weight=None, eval_set=None, eval_metric=None,
            early_stopping_rounds=None, learning_rates=None, verbose=True):
        # pylint: disable = attribute-defined-outside-init,arguments-differ, redefined-variable-type
        """
        Fit gradient boosting classifier

        Parameters
        ----------
        X : array_like
            Feature matrix
        y : array_like
            Labels
        sample_weight : array_like
            Weight for each instance
        eval_set : list, optional
            A list of (X, y) pairs to use as a validation set for
            early-stopping
        eval_metric : str, callable, optional
            If a str, should be a built-in evaluation metric to use. See
            doc/parameter.md. If callable, a custom evaluation metric. The call
            signature is func(y_predicted, y_true) where y_true will be a
            DMatrix object such that you may need to call the get_label
            method. It must return a str, value pair where the str is a name
            for the evaluation and value is the value of the evaluation
            function. This objective is always minimized.
        early_stopping_rounds : int, optional
            Activates early stopping. Validation error needs to decrease at
            least every <early_stopping_rounds> round(s) to continue training.
            Requires at least one item in evals.  If there's more than one,
            will use the last. Returns the model from the last iteration
            (not the best one). If early stopping occurs, the model will
            have three additional fields: bst.best_score, bst.best_iteration
            and bst.best_ntree_limit.
            (Use bst.best_ntree_limit to get the correct value if num_parallel_tree
            and/or num_class appears in the parameters)
        learning_rates: list or function
            List of learning rate for each boosting round
            or a customized function that calculates eta in terms of
            current number of round and the total number of boosting round (e.g. yields
            learning rate decay)
            - list l: eta = l[boosting round]
            - function f: eta = f(boosting round, num_boost_round)
        verbose : bool
            If `verbose` and an evaluation set is used, writes the evaluation
            metric measured on the validation set to stderr.
        """
        evals_result = {}
        self.classes_ = np.unique(y)
        self.n_classes_ = len(self.classes_)


        xgb_options = self.get_xgb_params()

        if callable(self.objective):
            obj = _objective_decorator(self.objective)
            # Use default value. Is it really not used ?
            xgb_options["objective"] = "binary:logistic"
        else:
            obj = None

        if self.n_classes_ > 2:
            # Switch to using a multiclass objective in the underlying XGB instance
            xgb_options["objective"] = "multi:softprob"
            xgb_options['num_class'] = self.n_classes_

        feval = eval_metric if callable(eval_metric) else None
        if eval_metric is not None:
            if callable(eval_metric):
                eval_metric = None
            else:
                xgb_options.update({"eval_metric": eval_metric})

        if eval_set is not None:
            # TODO: use sample_weight if given?
            evals = list(DMatrix(x[0], label=x[1], missing=self.missing) for x in eval_set)
            nevals = len(evals)
            eval_names = ["validation_{}".format(i) for i in range(nevals)]
            evals = list(zip(evals, eval_names))
        else:
            evals = ()

        self._features_count = X.shape[1]

        self._le = LabelEncoder().fit(y)
        training_labels = self._le.transform(y)

        if sample_weight is not None:
            train_dmatrix = DMatrix(X, label=training_labels, weight=sample_weight,
                                    missing=self.missing)
        else:
            train_dmatrix = DMatrix(X, label=training_labels,
                                    missing=self.missing)

        self._Booster = train(xgb_options, train_dmatrix, self.n_estimators,
                              evals=evals, learning_rates=learning_rates,
                              early_stopping_rounds=early_stopping_rounds,
                              evals_result=evals_result, obj=obj, feval=feval,
                              verbose_eval=verbose)

        if evals_result:
            for val in evals_result.items():
                evals_result_key = list(val[1].keys())[0]
                evals_result[val[0]][evals_result_key] = val[1][evals_result_key]
            self.evals_result_ = evals_result

        if early_stopping_rounds is not None:
            self.best_score = self._Booster.best_score
            self.best_iteration = self._Booster.best_iteration
            self.best_ntree_limit = self._Booster.best_ntree_limit

        return self

    def predict(self, data, output_margin=False, ntree_limit=0):
        test_dmatrix = DMatrix(data, missing=self.missing)
        class_probs = self.booster().predict(test_dmatrix,
                                             output_margin=output_margin,
                                             ntree_limit=ntree_limit)
        if len(class_probs.shape) > 1:
            column_indexes = np.argmax(class_probs, axis=1)
        else:
            column_indexes = np.repeat(0, class_probs.shape[0])
            column_indexes[class_probs > 0.5] = 1
        return self._le.inverse_transform(column_indexes)

    def predict_proba(self, data, output_margin=False, ntree_limit=0):
        test_dmatrix = DMatrix(data, missing=self.missing)
        class_probs = self.booster().predict(test_dmatrix,
                                             output_margin=output_margin,
                                             ntree_limit=ntree_limit)
        if self.objective == "multi:softprob":
            return class_probs
        else:
            classone_probs = class_probs
            classzero_probs = 1.0 - classone_probs
            return np.vstack((classzero_probs, classone_probs)).transpose()

    def evals_result(self):
        """Return the evaluation results.

        If eval_set is passed to the `fit` function, you can call evals_result() to
        get evaluation results for all passed eval_sets. When eval_metric is also
        passed to the `fit` function, the evals_result will contain the eval_metrics
        passed to the `fit` function

        Returns
        -------
        evals_result : dictionary

        Example
        -------
        param_dist = {'objective':'binary:logistic', 'n_estimators':2}

        clf = xgb.XGBClassifier(**param_dist)

        clf.fit(X_train, y_train,
                eval_set=[(X_train, y_train), (X_test, y_test)],
                eval_metric='logloss',
                verbose=True)

        evals_result = clf.evals_result()

        The variable evals_result will contain:
        {'validation_0': {'logloss': ['0.604835', '0.531479']},
         'validation_1': {'logloss': ['0.41965', '0.17686']}}
        """
        if self.evals_result_:
            evals_result = self.evals_result_
        else:
            raise XGBoostError('No results.')

        return evals_result

    @property
    def feature_importances_(self):
        """
        Returns
        -------
        feature_importances_ : array of shape = [n_features]

        """
        fs = self.booster().get_fscore()
        keys = [int(k.replace('f', '')) for k in fs.keys()]
        fs_dict = dict(zip(keys, fs.values()))
        all_features_dict = dict.fromkeys(range(0, self._features_count), 0)
        all_features_dict.update(fs_dict)
        all_features = np.fromiter(all_features_dict.values(), np.float32)
        return all_features / all_features.sum()


class XGBRegressor(XGBModel, XGBRegressorBase):
    # pylint: disable=missing-docstring
    __doc__ = """Implementation of the scikit-learn API for XGBoost regression.
    """ + '\n'.join(XGBModel.__doc__.split('\n')[2:])
