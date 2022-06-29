__all__ = [
    "SubGaussRDPtoDP",
    "ShuffGaussRDPtoDP",
    "SubShuffGaussRDPtoDP",
    "ApproxSCIGaussRDPtoDP",
]

import warnings
from functools import partial

import numpy as np
from tqdm import tqdm

from .utils import (eff_log_multinomial_coeff, findCombinations, fun_int,
                    get_binom_coeffs, stable_logsumexp, accel_asc)


def _check_delta(delta):
    if type(delta) != float:
        raise TypeError(f"delta must be float, found delta {type(delta)}")
    if delta < 0 or delta > 1:
        raise ValueError(f"delta must be between 0 and 1, found delta = {delta}")


def _check_lmbda(lmbda):
    if type(lmbda) != int:
        raise TypeError(f"lmbda must be integer, found lmbda {type(lmbda)}")
    if lmbda <= 1:
        raise ValueError(f"lmbda must be larger than 1, found delta = {lmbda}")


def shuffle_gauss_rdp(lmbda: int, sigma0: float = 1, n: int = 100):
    """Returns the shuffle gaussian RDP"""
    if lmbda > 100:
        warnings.warn("This will probably take a long time.")
    # partitions = []
    # findCombinations(lmbda, partitions)
    partitions = accel_asc(lmbda)
    multinom = []
    for parts in partitions:
        multicoeff = eff_log_multinomial_coeff(parts, n)
        square_of_part = sum([i**2 for i in parts])
        multinom.append(
            multicoeff
            + (square_of_part - lmbda) / (2 * sigma0**2)
            - lmbda * np.log(n)
        )
    return stable_logsumexp(multinom) / (lmbda - 1)


def _subshuff_gauss_rdp(lmbda: int, gamma: float, shuffRDPs: np.ndarray):
    """helper function for subssampled shuff gauss using theorem 9 of [wbk19]"""
    logBinomC = get_binom_coeffs(lmbda)

    lmbdas = np.linspace(1, lmbda, lmbda).astype(int)

    exp_eps2 = np.exp(shuffRDPs[1])
    min_term2 = np.min([4 * exp_eps2 - 4, 2 * exp_eps2])

    term2 = 2 * np.log(gamma) + logBinomC[lmbda, 2] + np.log(min_term2)

    termj = [
        j * np.log(gamma) + logBinomC[lmbda, j] + (j - 1) * shuffRDPs[j - 1]
        for j in lmbdas[2:]
    ]

    moments = [0] + [term2] + termj

    return stable_logsumexp(moments) / (lmbda - 1)


def subshuff_gauss_rdp(lmbda: int, sigma0: float = 1, n: int = 100, subno: int = 10):
    """subssampled shuff gauss using theorem 9 of [wbk19]
    use n and subsampled n as variables
    """
    gamma = subno / n  # subsampling rate

    lmbdas = np.linspace(1, lmbda, lmbda).astype(int)
    shuffRDPs = np.zeros_like(lmbdas, float)

    for i in lmbdas:
        if i > 1:
            shuffRDPs[i - 1] = shuffle_gauss_rdp(i, sigma0, n)

    return _subshuff_gauss_rdp(lmbda, gamma, shuffRDPs)


def get_subshuff_gauss_rdp(
    lmbda: int, sigma0: float = 1, gamma: float = 0.1, subno: int = 10
):
    """subssampled shuff gauss using theorem 9 of [wbk19]
    use gamma and subsampled n as variables
    """

    lmbdas = np.linspace(1, lmbda, lmbda).astype(int)
    shuffRDPs = np.zeros_like(lmbdas, float)

    for i in lmbdas:
        if i > 1:
            shuffRDPs[i - 1] = shuffle_gauss_rdp(i, sigma0, subno)

    return _subshuff_gauss_rdp(lmbda, gamma, shuffRDPs)


class ShuffGaussRDPtoDP:
    def __init__(
        self, sigma0: float, shuffn: int, m: int, verbose: bool = True
    ) -> None:
        self.shuffn = shuffn
        self.m = m  # max lmbda
        self.sigma0 = sigma0
        self.maxlmbdas = np.linspace(1, self.m, self.m).astype(int)
        self.RDPs_int = np.zeros_like(
            self.maxlmbdas, float
        )  # store shuffle rdp from **lmbda=1** without composition
        self.verbose = verbose

    def get_rdps(self, rdps_int: np.ndarray, rdp_func) -> np.ndarray:
        """get rdp as an array

        Args:
            rdps_int (int): initial array of rdp
            rdp_func (_type_): function that calculates rdp

        Returns:
            np.ndarray: _description_
        """
        if self.verbose:
            for i in tqdm(self.maxlmbdas):
                if i > 1:
                    rdps_int[i - 1] = rdp_func(i)
        else:
            for i in self.maxlmbdas:
                if i > 1:
                    rdps_int[i - 1] = rdp_func(i)
        return rdps_int

    def shuff(self, shuffn, rdps_int):
        self.shuffrdpfunc = partial(shuffle_gauss_rdp, sigma0=self.sigma0, n=shuffn)
        if rdps_int.any() == False:
            rdps_int = self.get_rdps(rdps_int, self.shuffrdpfunc)
        return rdps_int

    def get_shuff(self):
        """Run this before get eps"""
        self.RDPs_int = self.shuff(self.shuffn, self.RDPs_int)

    def get_eps(self, delta: float, coeff: int) -> tuple:  # minimize over \lambda
        """Get epsilon given delta and coeff (no of iter)
        it first calculate subshuff rdp for all moments
        """
        _check_delta(delta)

        if self.RDPs_int.any() == False:
            raise ValueError("The RDPs are not initialized! Run get_shuff first!")

        rdp2dp = [fun_int(i, delta, coeff, self.RDPs_int) for i in self.maxlmbdas]
        bestint = np.argmin(rdp2dp)

        if bestint == 0:
            if self.verbose:
                warnings.warn("Warning: Smallest lambda = 1.")

        if bestint == self.m - 1:
            if self.verbose:
                warnings.warn("Warning: Reach quadratic upper bound: m_max.")
        # In this case, we should increase m, but for now we leave it for future improvement

        bestlmbda = self.maxlmbdas[bestint]

        return rdp2dp[bestint], bestlmbda  # return eps, best lambda


class SubShuffGaussRDPtoDP(ShuffGaussRDPtoDP):
    """_summary_"""

    def __init__(
        self, sigma0: float, n: int, shuffn: int, m: int, verbose: bool = True
    ) -> None:
        super().__init__(sigma0, shuffn, m, verbose)
        self.n = n
        self.gamma = self.shuffn / n

    def subshuff(self, shuffn: int, rdps_int: np.ndarray):
        """subsample shuffle rdp.
        Calculate shuffle rdp up to max order if not calculated

        """
        self.subshufffunc = partial(
            get_subshuff_gauss_rdp, sigma0=self.sigma0, gamma=self.gamma, subno=shuffn
        )
        if rdps_int.any() == False:
            rdps_int = self.get_rdps(rdps_int, self.subshufffunc)
        return rdps_int

    def get_subshuff(self):
        self.RDPs_int = self.subshuff(self.shuffn, self.RDPs_int)

class SubGaussRDPtoDP(SubShuffGaussRDPtoDP):
    """Subsampled Gaussian (no shuffling effect)

    Args:
        SubShuffGaussRDPtoDP (_type_): _description_

    Returns:
        _type_: _description_
    """

    def __init__(self, sigma0: float, n: int, shuffn: int, m: int, verbose: bool = True) -> None:
        super().__init__(sigma0, n, shuffn, m, verbose)
    
    def shuff(self, shuffn, rdps_int):
        self.shuffrdpfunc = lambda x: x/(2*self.sigma0**2)
        if rdps_int.any() == False:
            rdps_int = self.get_rdps(rdps_int, self.shuffrdpfunc)
        return rdps_int


class ApproxSCIGaussRDPtoDP(SubShuffGaussRDPtoDP):
    """Approximate Shuffled Check-in Gaussian mechanism."""

    def __init__(
        self,
        sigma0,
        n: int,
        shuffn: int,
        m: int,
        error: float = 0.5,
        verbose: bool = True,
    ) -> None:
        super().__init__(sigma0, n, shuffn, m, verbose)
        # self.error = error
        self.displaced_n = int((1 - error) * shuffn) + 1
        # self.rdp = partial(shuffle_gauss_rdp, sigma0=self.sigma0, n=displaced_n)
        # self.single_rdp = partial(shuffle_gauss_rdp, sigma0=self.sigma0, n=1)
        self.single_subshuffRDPs_int = np.zeros_like(
            self.maxlmbdas, float
        )  # store rdp from lmbda=1
        self.subshuffRDPs_int = np.zeros_like(
            self.maxlmbdas, float
        )  # store rdp from lmbda=1
        self.chernoff_factor = -1 * self.shuffn * error**2 / 2

    def get_subshuff(self):
        if self.subshuffRDPs_int.any() == False:
            self.subshuffRDPs_int = self.subshuff(self.displaced_n, self.RDPs_int)
        if self.single_subshuffRDPs_int.any() == False:
            self.single_subshuffRDPs_int = self.subshuff(
                1, self.single_subshuffRDPs_int
            )
        if self.RDPs_int.any() == False:
            for i in self.maxlmbdas:
                if i > 1:
                    factor1 = [
                        (i - 1) * self.single_subshuffRDPs_int[i - 1]
                        + self.chernoff_factor
                    ]
                    factor2 = [(i - 1) * self.subshuffRDPs_int[i - 1]]
                    self.RDPs_int[i - 1] = stable_logsumexp(factor1 + factor2) / (i - 1)


class _SubShuffGaussRDPtoDP:
    """_summary_"""

    def __init__(
        self, sigma0: float, n: int, subno: int, m: int, verbose: bool = True
    ) -> None:
        """_summary_

        Args:
            sigma0 (float): _description_
            n (int): _description_
            subno (int): _description_
            m (int): _description_
            verbose (bool, optional): _description_. Defaults to True.
        """
        self.n = n
        self.m = m  # max lmbda
        self.sigma0 = sigma0
        self.maxlmbdas = np.linspace(1, self.m, self.m).astype(int)
        self.shuffRDPs_int = np.zeros_like(
            self.maxlmbdas, float
        )  # store shuffle rdp from **lmbda=1** without composition
        self.subshuffRDPs_int = np.zeros_like(
            self.maxlmbdas, float
        )  # store sub shuffle rdp from **lmbda=1** without composition
        self.subno = subno
        self.gamma = self.subno / n
        self.verbose = verbose
        self.rdp = partial(shuffle_gauss_rdp, sigma0=self.sigma0, n=self.subno)

    def get_shuffrdps(self, rdps_int: int, rdp_func) -> np.ndarray:
        """_summary_

        Args:
            rdps_int (int): _description_
            rdp_func (_type_): _description_

        Returns:
            np.ndarray: _description_
        """
        if self.verbose:
            for i in tqdm(self.maxlmbdas):
                if i > 1:
                    rdps_int[i - 1] = rdp_func(i)
        else:
            for i in self.maxlmbdas:
                if i > 1:
                    rdps_int[i - 1] = rdp_func(i)
        return rdps_int

    def subshuff(self, lmbda: int, gamma: float):
        """subsample shuffle rdp.
        Calculate shuffle rdp up to max order if not calculated

        """
        _check_lmbda(lmbda)

        if self.shuffRDPs_int.any() == False:
            self.shuffRDPs_int = self.get_shuffrdps(self.shuffRDPs_int, self.rdp)

        return _subshuff_gauss_rdp(lmbda, gamma, self.shuffRDPs_int)

    def get_eps(self, delta: float, coeff: int) -> tuple:  # minimize over \lambda
        """Get epsilon given delta and coeff (no of iter)
        it first calculate subshuff rdp for all moments
        """
        _check_delta(delta)

        if self.subshuffRDPs_int.any() == False:
            for i in self.maxlmbdas:
                if i > 1:
                    self.subshuffRDPs_int[i - 1] = self.subshuff(i, self.gamma)

        rdp2dp = [
            fun_int(i - 1, delta, coeff, self.subshuffRDPs_int) for i in self.maxlmbdas
        ]
        bestint = np.argmin(rdp2dp)

        if bestint == 0:
            if self.verbose:
                warnings.warn("Warning: Smallest lambda = 1.")

        if bestint == self.m - 1:
            if self.verbose:
                warnings.warn("Warning: Reach quadratic upper bound: m_max.")
        # In this case, we should increase m, but for now we leave it for future improvement

        bestlmbda = self.maxlmbdas[bestint]

        return rdp2dp[bestint], bestlmbda  # return eps, best lambda


class _ApproxSCIGaussRDPtoDP(_SubShuffGaussRDPtoDP):
    """Approximate Shuffled Check-in Gaussian mechanism."""

    def __init__(
        self,
        sigma0,
        n: int,
        subno: int,
        m: int,
        error: float = 0.5,
        verbose: bool = True,
    ) -> None:
        super().__init__(sigma0, n, subno, m, verbose)
        self.error = error
        displaced_n = int((1 - error) * subno) + 1
        self.rdp = partial(shuffle_gauss_rdp, sigma0=self.sigma0, n=displaced_n)
        # self.single_rdp = partial(shuffle_gauss_rdp, sigma0=self.sigma0, n=1)
        self.single_shuffRDPs_int = np.zeros_like(
            self.maxlmbdas, float
        )  # store rdp from lmbda=1
        self.single_subshuffRDPs_int = np.zeros_like(
            self.maxlmbdas, float
        )  # store rdp from lmbda=1
        self.shuffcheckinRDPs_int = np.zeros_like(
            self.maxlmbdas, float
        )  # store rdp from lmbda=1

    def single_subshuff(self, lmbda: int, gamma: float):
        """subsample shuffle rdp for single element.
        Calculate shuffle rdp up to max order if not calculated

        """
        assert lmbda > 1

        rdpfunc = partial(shuffle_gauss_rdp, sigma0=self.sigma0, n=1)

        if self.single_shuffRDPs_int.any() == False:
            self.single_shuffRDPs_int = self.get_shuffrdps(
                self.single_shuffRDPs_int, rdpfunc
            )

        return _subshuff_gauss_rdp(lmbda, gamma, self.single_shuffRDPs_int)

    def get_eps(self, delta, coeff):  # minimize over \lambda
        """Get epsilon given delta and coeff (no of iter)
        it first calculate subshuff rdp for all moments
        """

        _check_delta(delta)

        chernoff_factor = -1 * self.subno * self.error**2 / 2

        if self.subshuffRDPs_int.any() == False:
            for i in self.maxlmbdas:
                if i > 1:
                    self.subshuffRDPs_int[i - 1] = self.subshuff(i, self.gamma)

        if self.single_subshuffRDPs_int.any() == False:
            for i in self.maxlmbdas:
                if i > 1:
                    self.single_subshuffRDPs_int[i - 1] = self.single_subshuff(
                        i, self.gamma
                    )

        if self.shuffcheckinRDPs_int.any() == False:
            for i in self.maxlmbdas:
                if i > 1:
                    factor1 = [
                        (i - 1) * self.single_subshuffRDPs_int[i - 1] + chernoff_factor
                    ]
                    factor2 = [(i - 1) * self.subshuffRDPs_int[i - 1]]
                    self.shuffcheckinRDPs_int[i - 1] = stable_logsumexp(
                        factor1 + factor2
                    ) / (i - 1)

        rdp2dp = [
            fun_int(i - 1, delta, coeff, self.shuffcheckinRDPs_int)
            for i in self.maxlmbdas
        ]
        bestint = np.argmin(rdp2dp)

        if bestint == 0:
            if self.verbose:
                warnings.warn("Warning: Smallest lambda = 1.")

        if bestint == self.m - 1:
            if self.verbose:
                warnings.warn("Warning: Reach quadratic upper bound: m_max.")
        # In this case, we should increase m, but for now we leave it for future improvement

        bestlmbda = self.maxlmbdas[bestint]

        return rdp2dp[bestint], bestlmbda  # return eps, best lambda
