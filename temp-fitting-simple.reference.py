#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Dec 11 16:04:52 2025

@author: liuchang
"""

import imageio
import matplotlib.pyplot as plt
import os
import numpy as np
import glob
import pickle
import math
#from scipy.optimize import curve_fit as cf

wdir = '/Users/liuchang/OneDrive/experiment/spc-script/2025-11-21/Background Subtracted'  # contains background subtracted images
folder = "/SPI-new"
os.chdir(wdir)
#os.mkdir(wdir + '/Spectra-temp')

# counts_per_e = 6.4 #for gain = 1, readout rate = 5 MHz
counts_per_e = 4.9
kev_per_count = 3.66 / 1000  # [keV]

binwidth = 10
maxi = 10000  # arbitrary maximum count value

flux = []
filelist = []

# import filter transmission and QE data
f1 = open('/Users/liuchang/OneDrive/experiment/spc-script/metal-filter.pckl', 'rb')
energy, be, kap = pickle.load(f1)
f1.close()
energy = np.concatenate((energy, np.linspace(30100, 70000, 400)), axis=0) / 1000  # [keV] extend energy axis to 70keV
be = np.concatenate((be, np.ones(400) * be[len(be) - 1]), axis=0)  # extend vals to 70keV
kap = np.concatenate((kap, np.ones(400) * kap[len(kap) - 1]), axis=0)  # extend vals to 70keV

f2 = open('/Users/liuchang/OneDrive/experiment/spc-script/QE.pckl', 'rb')
qe = pickle.load(f2)
f2.close()


# define 1 temperature exponential function
def func(x, a1, cof1):
    return a1 * np.exp(-cof1 * x)


# %%
os.chdir(wdir + folder)
# for each tif file in wdir....
for index, image_file in enumerate(glob.glob('*.tif')):
    print('open', image_file)
    filelist.append(image_file)
    data = imageio.imread(image_file)

    # generate histogram binwidth = 1 count
    hist = []
    hist_data = np.zeros(maxi)
    for val in range(1, maxi):
        hist.append(len(data[data == val]))
    hist = np.array(hist)

    # bin whole image histogram
    hist_bin = np.zeros(math.ceil(len(hist_data) / binwidth))
    for num in range(0, len(hist_data) - 1):
        hist_bin[int(num / binwidth)] += hist[num]
    hist_bin = hist_bin / binwidth  # normalise for binwidth

    # %%
    length = len(hist)
    xaxis = np.linspace(1, length, length) * counts_per_e * kev_per_count - 0.3  # create x-axis [keV]
    be_fig = np.interp(xaxis, energy, be)   # Be transmission
    kap_fig = np.interp(xaxis, energy, kap)  # Kapton transmission
    qe_fig = np.interp(xaxis, energy, qe)   # CCD QE
    T_fig = 1 / (be_fig * kap_fig)
    response = np.divide(1, (be_fig * kap_fig * qe_fig))  # detector response
    spectrum = np.multiply(hist, response)  # corrected spectrum, binwidth 1 count

    len_bin = len(hist_bin)
    x_bin = np.linspace(1, len_bin, len_bin) * counts_per_e * kev_per_count * binwidth - 0.3  # [keV]
    be_bin = np.interp(x_bin, energy, be)
    kap_bin = np.interp(x_bin, energy, kap)
    qe_bin = np.interp(x_bin, energy, qe)
    T_bin = 1 / (be_bin * kap_bin)
    rep_bin = np.divide(1, (be_bin * kap_bin * qe_bin))
    spec_bin = np.multiply(hist_bin, rep_bin)

    err_bin = np.multiply(np.sqrt(hist_bin), rep_bin)
    err_bin = np.array(err_bin)
    flux.append(np.trapz(spec_bin, x_bin))

    # integrated counts per 13.6 mm **2
    flux.append(np.trapz(spec_bin, x_bin))

    # %%
    fig = plt.figure(index + 1)
    s1 = plt.semilogy(
        xaxis,
        spectrum,
        linestyle='none',
        marker='.',
        markersize=1,
        color='b'
    )
    p1 = plt.semilogy(
        x_bin,
        spec_bin,
        color='r',
        label='binned spectrum',
        drawstyle='steps-mid'
    )


    xmin = 1
    xmax = 35

    plt.xlim(9.4, 10.8)
    plt.ylim(1e2, 1e3)
    plt.xlabel('Photon Energy [keV]', fontsize=16)
    plt.ylabel('dN/dE', fontsize=16)
    legend = plt.legend(loc='upper right')
    plt.grid('true', 'both')
    plt.savefig(wdir + "/Spectra-temp/" + image_file, dpi=400)
    plt.close()
