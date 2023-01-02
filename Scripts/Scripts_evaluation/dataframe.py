import os, sys
import pysam
import pandas as pd
import numpy as np
from scipy.stats import *

# force PYTHONPATH to look into the project directory for modules
rootdir = os.path.dirname(os.getcwd())
scriptdir = rootdir+'/Applied_Bioinformatics_2022/Scripts'
sys.path.insert(0, os.getcwd())
sys.path.insert(1, scriptdir)

from Scripts.Scripts_evaluation import chunkvcf as chkvcf
from Scripts.Scripts_pooling.files import *

"""
Building pandas Dataframes from VCF-files for plotting
"""


class PandasMixedVCF(object):
    """
    Pandas objects and methods for manipulating VCF files. Any format.
    Implements pysam methods into Pandas structures.
    Drawback: extremely slow...
    """
    def __init__(self, vcfpath: FilePath, format: str = None, indextype: str = 'id'):
        """
        :param vcfpath:
        :param indextype: identifier for variants: 'id', 'chrom:pos'.
        Must be 'chrom:pos' if the input has been generated by Phaser
        """
        self.path = vcfpath
        self.fmt = format
        self.idx = indextype
        obj = pysam.VariantFile(self.path)
        self.samples = list(obj.header.samples)

    def load(self):
        # object returned can be read only once
        return pysam.VariantFile(self.path)

    @property
    def variants(self) -> pd.Index:
        """
        Read variants identifiers ordered as in the input file
        :return:
        """
        vcfobj = self.load()
        vars = []
        if self.idx == 'id':
            for var in vcfobj:
                vars.append(var.id)
        if self.idx == 'chrom:pos':
            for var in vcfobj:
                vars.append(':'.join([str(var.chrom), str(var.pos)]))

        return pd.Index(data=vars, dtype=str, name='variants')

    @property
    def af_info(self):
        vcfobj = self.load()
        vars = self.variants
        arr = np.zeros((len(vars), ), dtype=float)
        for i, var in enumerate(vcfobj):
            arr[i] = var.info['AF'][0]

        return pd.DataFrame(arr, index=vars, columns=['af_info'], dtype=float)

    @property
    def phases(self) -> pd.DataFrame:
        # TODO: if fmt GT
        vcfobj = self.load()
        vars = self.variants
        arr = np.zeros((len(vars), len(self.samples)), dtype=float)
        for i, var in enumerate(vcfobj):
            pass
            # arr[i, :] = var.gt_phases

        return pd.DataFrame(arr, index=vars, columns=self.samples, dtype=bool)

    def vcf2dframe(self) -> tuple:
        # TODO: deprecate
        """
       Throws the genotypes values of a VCF file into side-DataFrames.
       :return: two data frames, one for each allele of the genotype
       """
        vcfobj = self.load()
        vars = self.variants
        arr = np.empty((len(vars), len(self.samples), 2), dtype=int)
        for i, var in enumerate(vcfobj):
            arr[i, :, :] = np.array(g[self.fmt] for g in var.samples.values()).astype(float)
        # alleles 1
        df0 = pd.DataFrame(arr[:, :, 0], index=vars.rename('id'), columns=self.samples)
        # alleles 2
        df1 = pd.DataFrame(arr[:, :, 1], index=vars.rename('id'), columns=self.samples)

        return df0, df1

    def genotypes(self) -> pd.DataFrame:
        """
       Throws the formatted genotypes values of a VCF file into a DataFrame.
       :return: DataFrame
       """
        lines = chkvcf.PysamVariantCallGenerator(self.path, format=self.fmt)
        df = pd.DataFrame(lines, index=self.variants.rename('id'), columns=self.samples)

        return df

    def trinary_encoding(self) -> pd.DataFrame:
        vcfobj = self.load()
        vars = self.variants
        arr = np.empty((len(vars), len(self.samples)), dtype=float)
        if self.fmt.upper() == 'GT':
            missing = np.vectorize(lambda x: np.nan if x is None else x)
            for i, var in enumerate(vcfobj):
                # missing are read as None
                gts = np.array([g[self.fmt] for g in var.samples.values()]).astype(float)
                tri = missing(gts).sum(axis=-1)
                arr[i, :] = np.nan_to_num(tri, nan=-1)
        elif self.fmt.upper() == 'GL':
            gtnan = np.array([np.nan, np.nan, np.nan])
            gt0 = np.array([0., 0., 0.])
            gt1 = np.array([0., 1., 0.])
            gt2 = np.array([0., 0., 2.])
            for i, var in enumerate(vcfobj):
                # convert GL to trinary (assume log-GL format according to VCF4.1 specifications)
                missing = lambda x: gtnan if 0.0 not in x else (gt0 if x[0] == 0.0 else (gt1 if x[1] == 0.0 else gt2))
                gts = np.array([g[self.fmt] for g in var.samples.values()]).astype(float)
                tri = np.apply_along_axis(missing, -1, gts).sum(axis=-1)
                arr[i, :] = np.nan_to_num(tri, nan=-1)
        dftrinary = pd.DataFrame(arr, index=vars, columns=self.samples, dtype=int)

        return dftrinary

    def hexa_encoding(self) -> pd.DataFrame:
        """
        Encode the GT genotypes as follows:
            * 0, 0 -> 0.0
            * 0, 1 -> 1.0
            * 1, 1 -> 2.0
            * None, None -> -1.0
            * 1, None -> 0.5
            * 0, None -> -0.5
        """
        # TODO: fmt GT only!
        vcfobj = self.load()
        vars = self.variants
        arr = np.empty((len(vars), len(self.samples)), dtype=float)
        for i, var in enumerate(vcfobj):
            # missing are read as None
            gts = np.array([g[self.fmt] for g in var.samples.values()]).astype(float)
            arr[i, :] = np.nan_to_num(gts, nan=-0.5).sum(axis=-1)
        dfhexa = pd.DataFrame(arr, index=vars, columns=self.samples, dtype=float)

        return dfhexa

    @property
    def missing_rate(self):
        trico = self.trinary_encoding()
        trico[trico == -1] = np.nan
        func = lambda x: np.sum(np.isnan(x)) / len(x)
        miss = trico.apply(func, axis=1, raw=True)
        miss.rename('missing_rate', inplace=True)
        return miss.to_frame()

    @property
    def aaf(self):
        trico = self.trinary_encoding()
        trico[trico == -1] = np.nan
        # calculate alternate allele frequency from non-missing genotypes
        func = lambda x: np.nansum(x) / (2 * np.sum(~np.isnan(x)))
        aaf = trico.apply(func, axis=1, raw=True)
        aaf.rename('aaf', inplace=True)
        return aaf.to_frame()

    @property
    def het_rate(self):
        trico = self.trinary_encoding()
        trico[trico == -1] = np.nan
        func = lambda x: np.where(x == 1, 1, 0).sum() / np.sum(~np.isnan(x))
        het_ra = trico.apply(func, axis=1, raw=True)
        het_ra.rename('het_rate', inplace=True)
        return het_ra.to_frame()

    @property
    def hom_ref_rate(self):
        trico = self.trinary_encoding()
        trico[trico == -1] = np.nan
        func = lambda x: np.where(x == 0, 1, 0).sum() / np.sum(~np.isnan(x))
        hom_rr = trico.apply(func, axis=1, raw=True)
        hom_rr.rename('hom_ref_rate', inplace=True)
        return hom_rr.to_frame()

    @property
    def hom_alt_rate(self):
        trico = self.trinary_encoding()
        trico[trico == -1] = np.nan
        func = lambda x: np.where(x == 2, 1, 0).sum() / np.sum(~np.isnan(x))
        hom_aa = trico.apply(func, axis=1, raw=True)
        hom_aa.rename('hom_alt_rate', inplace=True)
        return hom_aa.to_frame()

    def concatcols(self, args):
        vars = self.variants.to_frame(name='variants')
        df = vars.join(args)
        df.drop('variants', axis=1, inplace=True)
        return df

    @staticmethod
    def aaf_to_maf(s: pd.Series, name: str = 'maf'):
        func = lambda x: x if x <= 0.5 else 1 - x
        mafs = s.apply(func).rename(name)
        return mafs

    @property
    def maf(self):
        dfaaf = self.aaf
        maf = self.aaf_to_maf(dfaaf['aaf'])
        return maf.to_frame()

    @property
    def maf_info(self):
        dfafinfo = self.af_info
        maf = self.aaf_to_maf(dfafinfo['af_info'], name='maf_info')
        return maf.to_frame()


class PandasMinorVCF(PandasMixedVCF):
    """
    Returns genotypes for minor allele carriers only (homozygotes for major are set to NaN).
    """

    # def __init__(self): inherited from parent class

    def trinary_encoding(self) -> pd.DataFrame:
        vcfobj = self.load()
        vars = self.variants
        af = self.af_info
        arr = np.empty((len(vars), len(self.samples)), dtype=float)
        if self.fmt.upper() == 'GT':
            missing = np.vectorize(lambda x: np.nan if x is None else x)
            for i, var in enumerate(vcfobj):
                # missing are read as None
                gts = np.array([g[self.fmt] for g in var.samples.values()]).astype(float)
                tri = missing(gts).sum(axis=-1)
                if af.iloc[i][0] <= 0.5:
                    tri[tri == 0] = np.nan
                else:
                    tri[tri == 2] = np.nan
                arr[i, :] = np.nan_to_num(tri, nan=-1)

        elif self.fmt.upper() == 'GL':
            gtnan = np.array([np.nan, np.nan, np.nan])
            gt0 = np.array([0., 0., 0.])
            gt1 = np.array([0., 1., 0.])
            gt2 = np.array([0., 0., 2.])
            for i, var in enumerate(vcfobj):
                # convert GL to trinary (assume log-GL format according to VCF4.1 specifications)
                missing = lambda x: gtnan if 0.0 not in x else (gt0 if x[0] == 0.0 else (gt1 if x[1] == 0.0 else gt2))
                gts = np.array([g[self.fmt] for g in var.samples.values()]).astype(float)
                tri = np.apply_along_axis(missing, -1, gts).sum(axis=-1)
                if af.iloc[i][0] <= 0.5:
                    tri[tri == 0] = np.nan
                else:
                    tri[tri == 2] = np.nan
                arr[i, :] = np.nan_to_num(tri, nan=-1)
        dftrinary = pd.DataFrame(arr, index=vars, columns=self.samples, dtype=int)

        return dftrinary