# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
# https://github.com/acphile/RTSGAN

import argparse
import pickle
import collections
import logging
import math
import os,sys,time
import random
from sys import maxsize
import pickle
import numpy as np
import torch
import torch.nn as nn
from utils.general import init_logger, make_sure_path_exists
sys.path.append('./general/')
from physionet2012 import Physio2012

DEBUG_SCALE = 512
# ===-----------------------------------------------------------------------===
# Argument parsing
# ===-----------------------------------------------------------------------===
parser = argparse.ArgumentParser()
parser.add_argument("--dataset", required=True, dest="dataset", help=".pkl file to use")     
parser.add_argument("--force", default="", dest="force", help="schedule")     
parser.add_argument("--devi", default="0", dest="devi", help="gpu")
parser.add_argument("--epochs", default=800, dest="epochs", type=int,
                    help="Number of full passes through training set for autoencoder")
parser.add_argument("--iterations", default=15000, dest="iterations", type=int,
                    help="Number of iterations through training set for WGAN")
parser.add_argument("--d-update", default=5, dest="d_update", type=int,
                    help="discriminator updates per generator update")
parser.add_argument("--log-dir", default="../2012_result", dest="log_dir",
                    help="Directory where to write logs / serialized models")
parser.add_argument("--task-name", default=time.strftime("%Y-%m-%d-%H-%M-%S"), dest="task_name",
                    help="Name for this task, use a comprehensive one")
parser.add_argument("--python-seed", dest="python_seed", type=int, default=random.randrange(maxsize),
                    help="Random seed of Python and NumPy")
parser.add_argument("--debug", dest="debug", default=False, action="store_true", help="Debug mode")
parser.add_argument("--fix-ae", dest="fix_ae", default=None, help="Test mode")
parser.add_argument("--fix-gan", dest="fix_gan", default=None, help="Test mode")

parser.add_argument("--ae-batch-size", default=128, dest="ae_batch_size", type=int,
                    help="Minibatch size for autoencoder")
parser.add_argument("--gan-batch-size", default=512, dest="gan_batch_size", type=int,
                    help="Minibatch size for WGAN")
parser.add_argument("--embed-dim", default=512, dest="embed_dim", type=int, help="dim of hidden state")
parser.add_argument("--hidden-dim", default=128, dest="hidden_dim", type=int, help="dim of GRU hidden state")
parser.add_argument("--layers", default=3, dest="layers", type=int, help="layers")
parser.add_argument("--ae-lr", default=1e-3, dest="ae_lr", type=float, help="autoencoder learning rate")
parser.add_argument("--weight-decay", default=0, dest="weight_decay", type=float, help="weight decay")
parser.add_argument("--dropout", default=0.0, dest="dropout", type=float,
                    help="Amount of dropout(not keep rate, but drop rate) to apply to embeddings part of graph")

parser.add_argument("--gan-lr", default=1e-4, dest="gan_lr", type=float, help="GAN learning rate")
parser.add_argument("--gan-alpha", default=0.99, dest="gan_alpha", type=float, help="for RMSprop")
parser.add_argument("--noise-dim", default=512, dest="noise_dim", type=int, help="dim of WGAN noise state")

options = parser.parse_args()

task_name = options.task_name
root_dir = f"{options.log_dir}/{task_name}"
#make_sure_path_exists(root_dir)
os.makedirs(root_dir, exist_ok=True)

devices=[int(x) for x in options.devi]
device = torch.device(f"cuda:{devices[0]}")  

# ===-----------------------------------------------------------------------===
# Set up logging
# ===-----------------------------------------------------------------------===
logger = init_logger(root_dir)

# ===-----------------------------------------------------------------------===
# Log some stuff about this run
# ===-----------------------------------------------------------------------===
logger.info(' '.join(sys.argv))
logger.info('')
print('Parameters:')
logger.info(options)

if options.debug:
    print("DEBUG MODE")
    options.epochs=11
    options.iterations=1

print(os.linesep)


random.seed(options.python_seed)
np.random.seed(options.python_seed % (2 ** 32 - 1))
logger.info(f'Python random seed: {options.python_seed}')
print(os.linesep)

# ===-----------------------------------------------------------------------===
# Read in dataset
# ===-----------------------------------------------------------------------===
dataset = pickle.load(open(options.dataset, "rb"))
train_set=dataset["train_set"]
dynamic_processor=dataset["dynamic_processor"]
static_processor=dataset["static_processor"]
train_set.set_input("dyn", "mask", "sta", "times", "lag", "seq_len","priv", "nex", "label")
                    
if options.debug:
    train_set = train_set[0:DEBUG_SCALE]
    
# ===-----------------------------------------------------------------------===
# Build model and trainer
# ===-----------------------------------------------------------------------===

params=vars(options)
params["static_processor"]=static_processor
params["dynamic_processor"]=dynamic_processor
params["root_dir"]=root_dir
params["logger"]=logger
params["device"]=device

print('maybe aegan params')
syn = Physio2012((static_processor, dynamic_processor), params)

if options.fix_ae is not None:
    print('load trained ae...')
    syn.load_ae(options.fix_ae)
else:
    print('training ae...')
    syn.train_ae(train_set, options.epochs)
    ## print(training logger here)
    print('ae trainig done', os.linesep)

print('start ae eval...')
h = syn.eval_ae(train_set)
with open(f"{root_dir}/hidden", "wb") as f:
    pickle.dump(h, f)
print('eval done and weight? (eval_ae method/hidden) saved', os.linesep)

print('generating ae...')
sta, dyn = syn.generate_ae(train_set)
## maybe print epoch? logger here
#make_sure_path_exists("{}/reconstruction".format(root_dir))
os.makedirs(f"{root_dir}/reconstruction", exist_ok=True)


for i, res in enumerate(dyn[:10]):
    res.to_csv(f"{root_dir}/reconstruction/p_{i}.psv", sep='\t', index=False)
logger.info("Finish eval ae")
print(os.linesep)
    
if dataset.get('val_set') is not None:
    print('validating...')
    val_set = dataset['val_set']
    val_set.set_input("dyn", "mask", "sta", "times", "lag", "seq_len","priv", "nex")
    h = syn.eval_ae(val_set)
    with open(f"{root_dir}/hidden", "wb") as f:
        pickle.dump(h, f)
    vs, vd = syn.generate_ae(val_set)
    #make_sure_path_exists("{}/val".format(root_dir))
    os.makedirs(f"{root_dir}/val", exist_ok=True)

    for i, res in enumerate(vd):
        res.to_csv(f"{root_dir}/val/p{i}.psv", sep='\t', index=False)
    logger.info("Finish val")
    print(os.linesep)
    
if options.fix_gan is not None:
    print('load trained gan...')
    syn.load_generator(options.fix_gan)
    print('load done', os.linesep)
else:
    print('training gan...')
    syn.train_gan(train_set, options.iterations, options.d_update)
    print('training done', os.linesep)

h = syn.gen_hidden(len(train_set))
with open(f"{root_dir}/gen_hidden", "wb") as f:
    pickle.dump(h, f)
print('gen_hidden saved', os.linesep)
    
logger.info("\n")
logger.info("Generating data!")
print(os.linesep)
result = syn.synthesize(len(train_set))
dataset["train_set"]=result
with open(f"{root_dir}/train_replaced_with_syn.pkl","wb") as f:
    pickle.dump(dataset, f)
print('real train data replaced to synthesized data and saved')
print('all training processed done')