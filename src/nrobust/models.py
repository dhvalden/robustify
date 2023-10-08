from nrobust.prototypes import Protomodel
from nrobust.prototypes import Protoresult
import pandas as pd
import numpy as np
from tqdm import tqdm
from joblib import Parallel, delayed
from nrobust.utils import simple_ols
from nrobust.bootstrap_utils import stripped_ols
from nrobust.utils import space_size
from nrobust.utils import all_subsets
from nrobust.figures import plot_results
from nrobust.utils import group_demean
from nrobust.prototypes import MissingValueWarning
import _pickle
import warnings
from sklearn.model_selection import KFold
from sklearn.metrics import mean_squared_error


class OLSResult(Protoresult):
    """
    Result class containing the the output of the OLSRobust class.

    Parameters:
        y (str): The name of the dependent variable.
        specs (list of str): List of specification names.
        all_predictors (list of lists of str): List of predictor variable names for each specification.
        controls (list of str): List of control variable names.
        draws (int): Number of draws in the analysis.
        estimates (pd.DataFrame): DataFrame containing regression coefficient estimates.
        all_b (list of lists): List of coefficient estimates for each specification and draw.
        all_p (list of lists): List of p-values for each specification and draw.
        p_values (pd.DataFrame): DataFrame containing p-values for coefficient estimates.
        ll_array (list): List of log-likelihood values for each specification.
        aic_array (list): List of AIC values for each specification.
        bic_array (list): List of BIC values for each specification.
        hqic_array (list): List of HQIC values for each specification.
        av_k_metric_array (list, optional): List of average Kullback-Leibler divergence metrics.

    Methods:
        save(filename):
            Save the OLSResult object to a file using pickle.

        load(filename):
            Load an OLSResult object from a file using pickle.

        summary():
            Placeholder for a method to generate a summary of the OLS results.

        plot(specs=None, ic=None, colormap=None, colorset=None, figsize=(12, 6)):
            Generate plots of the OLS results.

        compute_bma():
            Perform Bayesian model averaging using BIC implied priors and return the results.

        merge(result_obj, prefix):
            Merge two OLSResult objects into one.

    Attributes:
        y_name (str): The name of the dependent variable.
        specs_names (pd.Series): Series containing specification names.
        all_predictors (list of lists of str): List of predictor variable names for each specification.
        controls (list of str): List of control variable names.
        draws (int): Number of draws in the analysis.
        estimates (pd.DataFrame): DataFrame containing regression coefficient estimates.
        p_values (pd.DataFrame): DataFrame containing p-values for coefficient estimates.
        all_b (list of lists): List of coefficient estimates for each specification and draw.
        all_p (list of lists): List of p-values for each specification and draw.
        summary_df (pd.DataFrame): DataFrame containing summary statistics of coefficient estimates.
        summary_bma (pd.DataFrame, optional): DataFrame containing Bayesian model averaging results.
    """
    def __init__(self, *,
                 y,
                 specs,
                 all_predictors,
                 controls,
                 draws,
                 estimates,
                 all_b,
                 all_p,
                 p_values,
                 ll_array,
                 aic_array,
                 bic_array,
                 hqic_array,
                 av_k_metric_array=None):
        super().__init__()
        self.y_name = y
        self.specs_names = pd.Series(specs)
        self.all_predictors = all_predictors
        self.controls = controls
        self.draws = draws
        self.estimates = pd.DataFrame(estimates)
        self.p_values = pd.DataFrame(p_values)
        self.all_b = all_b
        self.all_p = all_p
        self.summary_df = self._compute_summary()
        self.summary_df['ll'] = pd.Series(ll_array)
        self.summary_df['aic'] = pd.Series(aic_array)
        self.summary_df['bic'] = pd.Series(bic_array)
        self.summary_df['hqic'] = pd.Series(hqic_array)
        self.summary_df['av_k_metric'] = pd.Series(av_k_metric_array)
        self.summary_df['spec_name'] = self.specs_names
        self.summary_df['y'] = self.y_name

    def save(self, filename):
        """
        Saves the OLSResult object to a binary file.

        Args:
            filename (str): Name of the file to which the object will be saved.
        """
        with open(filename, 'wb') as f:
            _pickle.dump(self, f, -1)

    @classmethod
    def load(cls, filename):
        """
        Loads an OLSResult object from a binary file.

        Args:
            filename (str): Name of the file from which the object will be loaded.

        Returns:
            OLSResult: Loaded OLSResult object.
        """
        with open(filename, 'rb') as f:
            return _pickle.load(f)

    def summary(self):
        """
        Generates a summary of the regression results (not implemented).
        """
        pass

    def plot(self,
             specs=None,
             ic=None,
             colormap=None,
             colorset=None,
             figsize=(12, 6)):
        """
        Plots the regression results using specified options.

        Args:
            specs (list, optional): List of specification names to include in the plot.
            ic (str, optional): Information criterion to use for model selection (e.g., 'bic', 'aic').
            colormap (str, optional): Colormap to use for the plot.
            colorset (list, optional): List of colors to use for different specifications.
            figsize (tuple, optional): Size of the figure (width, height) in inches.

        Returns:
            matplotlib.figure.Figure: Plot showing the regression results.
        """
        return plot_results(results_object=self,
                            specs=specs,
                            ic=ic,
                            colormap=colormap,
                            colorset=colorset,
                            figsize=figsize)

    def _compute_summary(self):
        """
        Computes summary statistics based on coefficient estimates.

        Returns:
            pd.DataFrame: DataFrame containing summary statistics.
        """
        data = self.estimates.copy()
        out = pd.DataFrame()
        out['median'] = data.median(axis=1)
        out['max'] = data.max(axis=1)
        out['min'] = data.min(axis=1)
        out['ci_up'] = data.quantile(q=0.975, axis=1,
                                     interpolation='nearest')
        out['ci_down'] = data.quantile(q=0.025, axis=1,
                                       interpolation='nearest')
        return out

    def compute_bma(self):
        """
        Performs Bayesian Model Averaging (BMA) using BIC implied priors.

        Returns:
            pd.DataFrame: DataFrame containing BMA results.
        """
        likelihood_per_var = []
        weigthed_coefs = []
        max_ll = np.max(-self.summary_df.bic/2)
        shifted_ll = (-self.summary_df.bic/2) - max_ll
        models_likelihood = np.exp(shifted_ll)
        sum_likelihoods = np.nansum(models_likelihood)
        coefs = [[i[0] for i in x] for x in self.all_b]
        coefs = [i for sl in coefs for i in sl]
        var_names = [i for sl in self.all_predictors for i in sl]
        coefs_df = pd.DataFrame({'coef': coefs, 'var_name': var_names})
        for ele in self.controls:
            idx = []
            for spec in self.specs_names:
                idx.append(ele in spec)
            likelihood_per_var.append(np.nansum(models_likelihood[idx]))
            coefs = coefs_df[coefs_df.var_name == ele].coef.to_numpy()
            likelihood = models_likelihood[idx]
            weigthed_coef = coefs * likelihood
            weigthed_coefs.append(np.nansum(weigthed_coef))
        probs = likelihood_per_var / sum_likelihoods
        final_coefs = weigthed_coefs / sum_likelihoods
        summary_bma = pd.DataFrame({
            'control_var': self.controls,
            'probs': probs,
            'average_coefs': final_coefs
        })
        return summary_bma
    
    def merge(self, result_obj, prefix):
        """
        Merges two OLSResult objects into one.

        Args:
            result_obj (OLSResult): OLSResult object to be merged.
            prefix (str): Prefix to differentiate columns from different OLSResult objects.

        Raises:
            TypeError: If the input object is not an instance of OLSResult.
        """
        if not isinstance(result_obj, OLSResult):
            raise TypeError('Invalid object type. Expected an instance of OLSResult.')
        prefix = prefix
        

class OLSRobust(Protomodel):
    """
    Class for multi-variate regression using OLS

    Parameters
    ----------
    y : str
     Name of the dependent variable.
    x : str or list<str>
     List of names of the independent variable(s).
    data : DataFrame
     DataFrame contaning all the data to be used in the model.

    Returns
    -------
    self : Object
        An object containing the key metrics.
    """

    def __init__(self, *, y, x, data):
        """
        Initialize the OLSRobust object.

        Parameters
        ----------
        y : str
            Name of the dependent variable.
        x : str or list<str>
            List of names of the independent variable(s).
        data : DataFrame
            DataFrame containing all the data to be used in the model.
        """
        super().__init__()
        if data.isnull().values.any():
            warnings.warn('Missing values found in data. Listwise deletion will be applied',
                          MissingValueWarning)
        self.y = y
        self.x = x
        self.data = data
        self.results = None

    def get_results(self):
        """
        Get the results of the OLS regression.

        Returns
        -------
        results : OLSResult
            Object containing the regression results.
        """
        return self.results

    def multiple_y(self):
        """
        Cumputes composity y based on multiple indicators provided.
        """
        self.y_specs = []
        self.y_composites = []
        print("Calculating Composite Ys")
        for spec, index in zip(all_subsets(self.y),
                               tqdm(range(0, space_size(self.y)))):
            if len(spec) > 1:
                subset = self.data[list(spec)]
                subset = (subset-subset.mean())/subset.std()
                self.y_composites.append(subset.mean(axis=1))
                self.y_specs.append(spec)

    def fit(self,
            *,
            controls,
            group: str = None,
            draws=500,
            sample_size=None,
            replace=False,
            kfold=None,
            shuffle=False):
        """
        Fit the OLS models into the specification space as well as over the bootstrapped samples.

        Parameters
        ----------
        controls : list<str>
            List containing all the names of the possible control variables of the model.
        sample_size : int
            Number of bootstrap samples to collect.
        group : str
            Grouping variable. If provided, a Fixed Effects model is estimated.
        draws : int, optional
            Number of draws for bootstrapping. Default is 500.
        replace : bool, optional
            Whether to use replacement during bootstrapping. Default is False.
        kfold : int, optional
            Number of folds for k-fold cross-validation. Default is None.
        shuffle : bool, optional
            Whether to shuffle y variable to estimate joint significance test. Default is False.

        Returns
        -------
        self : Object
            Object class OLSRobust containing the fitted estimators.
        """
        if sample_size is None:
            sample_size = self.data.shape[0]

        if len(self.y) > 1:
            self.multiple_y()
            list_all_predictors = []
            list_b_array = []
            list_p_array = []
            list_ll_array = []
            list_aic_array = []
            list_bic_array = []
            list_hqic_array = []
            list_av_k_metric_array = []
            y_names = []
            specs = []
            for y, y_name in zip(self.y_composites,
                                 self.y_specs):
                space_n = space_size(controls)
                b_array = np.empty([space_n, draws])
                p_array = np.empty([space_n, draws])
                ll_array = np.empty([space_n])
                aic_array = np.empty([space_n])
                bic_array = np.empty([space_n])
                hqic_array = np.empty([space_n])
                all_predictors = []
                av_k_metric_array = np.empty([space_n])

                for spec, index in zip(all_subsets(controls),
                                       tqdm(range(0, space_n))):
                    if len(spec) == 0:
                        comb = self.data[self.x]
                    else:
                        comb = self.data[self.x + list(spec)]
                    if group:
                        comb = self.data[self.x + [group] + list(spec)]

                    comb = pd.concat([y, comb], axis=1)
                    comb = comb.dropna()

                    if group:
                        comb = group_demean(comb, group=group)
                    (b_all, p_all, ll_i,
                     aic_i, bic_i, hqic_i,
                     av_k_metric_i) = self._full_sample_OLS(comb,
                                                            kfold=kfold)
                    b_list, p_list = (zip(*Parallel(n_jobs=-1)
                                          (delayed(self._strap_OLS)
                                           (comb,
                                            group,
                                            sample_size,
                                            replace,
                                            shuffle)
                                           for i in range(0,
                                                          draws))))
                    y_names.append(y_name)
                    specs.append(frozenset(list(y_name) + list(spec)))
                    all_predictors.append(self.x + list(spec) + ['const'])
                    b_array[index, :] = b_list
                    p_array[index, :] = p_list
                    ll_array[index] = ll_i
                    aic_array[index] = aic_i
                    bic_array[index] = bic_i
                    hqic_array[index] = hqic_i
                    av_k_metric_array[index] = av_k_metric_i

                list_all_predictors.append(all_predictors)
                list_b_array.append(b_array)
                list_p_array.append(p_array)
                list_ll_array.append(ll_array)
                list_aic_array.append(aic_array)
                list_bic_array.append(bic_array)
                list_hqic_array.append(hqic_array)
                list_av_k_metric_array.append(av_k_metric_array)

            results = OLSResult(
                y=y_names,
                specs=specs,
                all_predictors=list_all_predictors,
                controls=controls,
                draws=draws,
                all_b=b_all,
                all_p=p_all,
                estimates=np.vstack(list_b_array),
                p_values=np.vstack(list_p_array),
                ll_array=np.hstack(list_ll_array),
                aic_array=np.hstack(list_aic_array),
                bic_array=np.hstack(list_bic_array),
                hqic_array=np.hstack(list_hqic_array),
                av_k_metric_array=np.hstack(list_av_k_metric_array)
                )

            self.results = results

        else:
            space_n = space_size(controls)
            specs = []
            all_predictors = []
            b_all_list = []
            p_all_list = []
            b_array = np.empty([space_n, draws])
            p_array = np.empty([space_n, draws])
            ll_array = np.empty([space_n])
            aic_array = np.empty([space_n])
            bic_array = np.empty([space_n])
            hqic_array = np.empty([space_n])
            av_k_metric_array = np.empty([space_n])
            for spec, index in zip(all_subsets(controls),
                                   tqdm(range(0, space_n))):
                if len(spec) == 0:
                    comb = self.data[self.y + self.x]
                else:
                    comb = self.data[self.y + self.x + list(spec)]
                if group:
                    comb = self.data[self.y + self.x + [group] + list(spec)]

                comb = comb.dropna()

                if group:
                    comb = group_demean(comb, group=group)
                (b_all, p_all, ll_i,
                 aic_i, bic_i, hqic_i,
                 av_k_metric_i) = self._full_sample_OLS(comb,
                                                        kfold=kfold)
                b_list, p_list = (zip(*Parallel(n_jobs=-1)
                                      (delayed(self._strap_OLS)
                                       (comb,
                                        group,
                                        sample_size,
                                        replace,
                                        shuffle)
                                       for i in range(0,
                                                      draws))))

                specs.append(frozenset(spec))
                all_predictors.append(self.x + list(spec) + ['const'])
                b_array[index, :] = b_list
                p_array[index, :] = p_list
                ll_array[index] = ll_i
                aic_array[index] = aic_i
                bic_array[index] = bic_i
                hqic_array[index] = hqic_i
                av_k_metric_array[index] = av_k_metric_i
                b_all_list.append(b_all)
                p_all_list.append(p_all)

            results = OLSResult(y=self.y[0],
                                specs=specs,
                                all_predictors=all_predictors,
                                controls=controls,
                                draws=draws,
                                all_b=b_all_list,
                                all_p=p_all_list,
                                estimates=b_array,
                                p_values=p_array,
                                ll_array=ll_array,
                                aic_array=aic_array,
                                bic_array=bic_array,
                                hqic_array=hqic_array,
                                av_k_metric_array=av_k_metric_array)

            self.results = results

    def _predict(self, x_test, betas):
        """
        Predict the dependent variable based on the test data and coefficients.

        Parameters
        ----------
        x_test : array-like
            Test data for independent variables.
        betas : array-like
            Coefficients obtained from the regression.

        Returns
        -------
        y_pred : array
            Predicted values for the dependent variable.
        """
        return np.dot(x_test, betas)

    def _full_sample_OLS(self,
                         comb_var,
                         kfold):
        """
        Call stripped_ols() over the full data containing y, x, and controls.

        Parameters
        ----------
        comb_var : Array
            ND array-like object containing the data for y, x, and controls.
        kfold : Boolean
            Whether or not to calculate k-fold cross-validation.

        Returns
        -------
        beta : float
            Estimate for x.
        p : float
            P value for x.
        AIC : float
            Akaike information criteria value for the model.
        BIC : float
            Bayesian information criteria value for the model.
        HQIC : float
            Hannan-Quinn information criteria value for the model.
        """
        y = comb_var.iloc[:, [0]]
        x = comb_var.drop(comb_var.columns[0], axis=1)
        out = simple_ols(y=y,
                         x=x)
        av_k_metric = None
        if kfold:
            k_fold = KFold(kfold)
            metrics = []
            for k, (train, test) in enumerate(k_fold.split(x, y)):
                out_k = simple_ols(y=y.loc[train],
                                   x=x.loc[train])
                y_pred = self._predict(x.loc[test], out_k['b'])
                y_true = y.loc[test]
                k_rmse = mean_squared_error(y_true, y_pred, squared=False)
                metrics.append(k_rmse)
            av_k_metric = np.mean(metrics)
        return (out['b'],
                out['p'],
                out['ll'][0][0],
                out['aic'][0][0],
                out['bic'][0][0],
                out['hqic'][0][0],
                av_k_metric)

    def _strap_OLS(self,
                   comb_var,
                   group,
                   sample_size,
                   replace,
                   shuffle):
        """
        Call stripped_ols() over a random sample of the data containing y, x, and controls.

        Parameters
        ----------
        comb_var : Array
            ND array-like object containing the data for y, x, and controls.
        group : str
            Grouping variable. If provided, sampling is performed over the group variable.
        sample_size : int
            Sample size to use in the bootstrap.
        replace : bool
            Whether to use replacement on sampling.
        shuffle : bool
            Whether to shuffle y var to estimate joint significant test.

        Returns
        -------
        beta : float
            Estimate for x.
        p : float
            P value for x.
        """
        temp_data = comb_var.copy()

        if shuffle:
            y = temp_data.iloc[:, [0]]
            idx_y = np.random.permutation(y.index)
            y = pd.DataFrame(y.iloc[idx_y]).reset_index(drop=True)
            x = temp_data.drop(temp_data.columns[0], axis=1)
            temp_data = pd.concat([y, x], axis=1)

        if group is None:
            samp_df = temp_data.sample(n=sample_size, replace=replace)
            # @TODO generalize the frac to the function call
            y = samp_df.iloc[:, [0]]
            x = samp_df.drop(samp_df.columns[0], axis=1)
            output = stripped_ols(y, x)
            b = output['b']
            p = output['p']
            return b[0][0], p[0][0]
        else:
            idx = np.random.choice(temp_data[group].unique(), sample_size)
            select = temp_data[temp_data[group].isin(idx)]
            no_singleton = select[select.groupby(group).transform('size') > 1]
            no_singleton = no_singleton.drop(columns=[group])
            y = no_singleton.iloc[:, [0]]
            x = no_singleton.drop(no_singleton.columns[0], axis=1)
            output = stripped_ols(y, x)
            b = output['b']
            p = output['p']
            return b[0][0], p[0][0]
