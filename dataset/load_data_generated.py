import torch
from torch import nn
import os

import tqdm
from tqdm import tqdm

import networkx as nx
import numpy as np

import matplotlib.pyplot as plt
import pickle
import re
import glob
import numpy as np
from torch.utils.data import Dataset, DataLoader, random_split
from types import MethodType

from torch_geometric.data import Batch, Data

import torch.nn.functional as F
from torch.nn import Module, Parameter, ModuleList, Linear

device = 'cuda' #@param ['cuda', 'cpu'] {'type':'string'}

from scipy.sparse.csgraph import laplacian
from numpy import linalg as LA

from collections import defaultdict
import math 
import sklearn

from utils.eval_helper import degree_stats, clustering_stats, orbit_stats_all, eval_fraction_unique, eval_fraction_unique_non_isomorphic_valid, spectral_stats

from utils.eval_helper_torch import degree_stats, clustering_stats, spectral_stats
 

class LaplacianDatasetNX(Dataset):
     
    def __init__(self,dataset,ds_filename,point_dim=7, smallest=True, split='all', scaler="standard", nodefeatures=False, device="cpu"):
        
        self.point_dim = point_dim
        self.samples = []
        # print('Point dim {}'.format(self.point_dim))
        self.label = []
        filename = f"{ds_filename}_{point_dim}_sm{smallest}_sc{scaler}_nf{nodefeatures}.torch"
        if not os.path.isfile(filename):
            print(ds_filename)
            with open( ds_filename+'.pkl', "rb") as f:
                 graph_list = pickle.load(f)
            
            graph_list = graph_list
            print('Comp dimensions...')
            
            indices = list(range(len(graph_list)))
            maxdimensions = max(g.number_of_nodes() for g in graph_list)
            print(f"Max # nodes: {maxdimensions}")
            
            print('Comp stats...')
            ori_eigenvalues = []       
            eigen_dic = defaultdict(dict)
            
            
            try:
                aaa
                eigen_dic = torch.load(ds_filename+'.eigen')
                print("Loaded precomuted eigenquantities")
            
            except:
    
                for ids,indiceori in enumerate(indices):
    
                    H = graph_list[indiceori].copy()
    
                    dims = (nx.adjacency_matrix(H)).shape    
                    adj = nx.adjacency_matrix(H).todense()
                    lap = laplacian(adj)                
                    w, v = LA.eigh(lap)
    
                    eigen_dic[ids]['w']=w
                    eigen_dic[ids]['v']=v
                    eigen_dic[ids]['dims']=dims
                    eigen_dic[ids]['lap']=lap
                    eigen_dic[ids]['A']=adj
    
#                 torch.save(eigen_dic,ds_filename+'.eigen')
            
            self.mu = 0#mu
            self.std = 1#std
            
            print('Comp Samples...')
            
            ids_list = eigen_dic.keys()
            
            
            self.edge_features = 0
            self.node_features = 0
            edge_labels = [None]*len(graph_list)
            if nodefeatures:
                node_labels = [torch.tensor([G.nodes[i]['x'] for i in range(len(G.nodes))]) for G in graph_list]
                num_labels = torch.cat(node_labels,-1).max()+1
                node_labels = [torch.nn.functional.one_hot(l, num_labels) for l in node_labels]
                self.node_features = num_labels
                
                num_labels = max([max([e['e'] for e in g.edges.values()]) for g in graph_list])+1
                edge_labels = [[(k,e['e']) for k,e in g.edges.items()] for g in graph_list]
                self.edge_features = num_labels
                
            for ids,indiceori in enumerate(indices): 
                label = []
     
                w = eigen_dic[ids]['w']
                v = eigen_dic[ids]['v']
                dims = eigen_dic[ids]['dims']
                lap = eigen_dic[ids]['lap'] 
                A = eigen_dic[ids]['A']

                eigva_ids_sort = w.argsort()[::-1]# descending order  
                eigva = w[eigva_ids_sort]

                if not smallest:
                    eigva = eigva[:point_dim]
                else:
                    eigva = eigva[-(1+point_dim):-1]

                eigva_norm = eigva#np.zeros(eigva.shape)

#                 for jj,value in enumerate(eigva):                      
#                       eigva_norm[jj] = minmax_norm(value, maxval[jj], minval[jj] ) 

                if not smallest:
                    eigvec = v[:,eigva_ids_sort][:,:point_dim] # v[:,i] is the eigenvector corresponding to the eigenvalue w[i]
                else:
                    eigvec = v[:,eigva_ids_sort][:,-(1+point_dim):-1] # v[:,i] is the eigenvector corresponding to the eigenvalue w[i]

                ################ if the graph is smaller than point_dim, add leading zero evals and evecs #############
                k = eigvec.shape[-1]
                left_pad = point_dim-k
                    
                eigvec = np.pad(eigvec, ((0,0),(left_pad, 0)), mode='constant')    
                eigva_norm = np.pad(eigva_norm, ((left_pad, 0)), mode='constant')    
                    
                ################ if we have labels, append them to eigenvectos ###################
                if nodefeatures:
                    eigvec = np.concatenate([eigvec,node_labels[indiceori]],-1)
                    eigva_norm = np.concatenate([eigva_norm,node_labels[indiceori][0]*0],-1)

                num_zeros = maxdimensions-dims[0]   
                n_nodes = dims[0]

                arr_pad = np.pad(lap, [(0, num_zeros), (0, num_zeros)], mode='constant')  

                eigvec = np.pad(eigvec, [(0, num_zeros), (0, 0)], mode='constant')    
                A = np.pad(A, [(0, num_zeros), (0, num_zeros)], mode='constant')  

                self.samples.append((torch.tensor(label).float(),torch.tensor(eigvec).float(),
                                     torch.tensor(eigva_norm).float(),torch.tensor(arr_pad).float(),
                                     edge_labels[indiceori],torch.tensor(n_nodes),torch.tensor(A).float()))
            
            print('SAVING Tot #{}'.format(len(self.samples))  )
            torch.save((self.samples,self.edge_features,self.node_features),filename)
        else:
            self.samples,self.edge_features,self.node_features = torch.load(filename)
            
        # print('Tot #{}'.format(len(self.samples))  )
 
            
        #train test
        test_len = int(len(self.samples)*0.2)
        train_len = len(self.samples) - test_len
        train_set, test_set = random_split(torch.arange(len(self.samples)), [train_len, test_len], generator=torch.Generator().manual_seed(1234))
        
        train_train_len = int(train_len*0.8)
        train_val_len = train_len-train_train_len
        train_train_set, train_val_set = random_split(train_set, [train_train_len, train_val_len], generator=torch.Generator().manual_seed(1234))

        if dataset=="zinc":
            print("ZINC STANDARD SPLITS")
            test_len = 5000
            train_len = 220011 + 24445
            train_set = torch.arange(train_len)
            test_set = torch.arange(test_len) + train_len
            
            train_train_len = 220011
            train_val_len = 24445
            train_train_set = torch.arange(train_train_len)
            train_val_set = torch.arange(train_val_len) + train_train_len
            
        #rescale data
        train_evecs = torch.stack([self.samples[i][1] for i in train_set],0)
        train_evals = torch.stack([self.samples[i][2] for i in train_set],0)
        
        if scaler=="standard":
            scaler_class = sklearn.preprocessing.StandardScaler
        if scaler=="minmax":
            scaler_class = lambda : sklearn.preprocessing.MinMaxScaler((-1,1))

        
        Lscaler = scaler_class()
        Lscaler.fit(train_evals)
        
        Wscaler = scaler_class()
        Wscaler.fit(train_evecs.reshape(-1,train_evecs.shape[-1]))
                
            
        if scaler=="standard":
            def scale_xy(self,x,y):
                wm_,ws_,lm_,ls_ = [t.to(x.device) for t in [self.wm,self.ws,self.lm,self.ls]]
                x = (x-wm_)/ws_
                y = (y-lm_)/ls_
                return x,y

            def unscale_xy(self,x,y, masked=True):
                # print(f"IN: {x.shape} {y.shape}") 
                if masked:
                    mask  = x.abs().sum(-1)[...,None]>1e-8
                    emask = y.abs() > 1e-8
                
                wm_,ws_,lm_,ls_ = [t.to(x.device) for t in [self.wm,self.ws,self.lm,self.ls]]
                x = x*ws_ + wm_
                y = y*ls_ + lm_

                # print(x.shape)
                # print(mask.shape)
                # print(emask.shape)
                if masked:
                    x  = mask  * x #* emask.squeeze(-2).unsqueeze(-2)
                    # y = emask * y                
                # print(f"OUT: {x.shape} {y.shape}")
                
                return x,y
            
            self.scale_xy = MethodType(scale_xy,self)
            self.unscale_xy = MethodType(unscale_xy,self)
            
            self.wm = torch.tensor(Wscaler.mean_)[None,:].float()
            self.ws = torch.tensor(Wscaler.var_)[:].float()**0.5+1e-12

            self.lm = torch.tensor(Lscaler.mean_)[:].float()
            self.ls = torch.tensor(Lscaler.var_)[:].float()**0.5+1e-12

        elif scaler=='minmax':
            
            def scale_xy(self, x, y):
                wm_,wr_,lm_,lr_ = [t.to(x.device) for t in [self.wm,self.wr,self.lm,self.lr]]
                x = (x-wm_)/wr_*2-1
                y = (y-lm_)/lr_*2-1
                return x,y

            
            def unscale_xy(self, x, y, mask=True):
                if masked:
                    mask  = x.abs().sum(-1)[...,None]>1e-8
                    emask = y.abs() > 1e-8

                wm_,wr_,lm_,lr_ = [t.to(x.device) for t in [self.wm,self.wr,self.lm,self.lr]]
                x = wr_*(x+1)/2 + wm_
                y = lr_*(y+1)/2 + lm_

                if masked:
                    x  = mask  * x * emask.squeeze(-2).unsqueeze(-2)
                    y = emask * y   

                return x, y
            
#             setattr(LaplacianDatasetNX, 'scale_xy',scale_xy)
#             setattr(LaplacianDatasetNX, 'unscale_xy',unscale_xy)
            self.scale_xy = MethodType(scale_xy,self)
            self.unscale_xy = MethodType(unscale_xy,self)
            
            self.wm = torch.tensor(Wscaler.data_min_)[None,:].float()
            self.wr = torch.tensor(Wscaler.data_range_)[:].float()+1e-12

            self.lm = torch.tensor(Lscaler.data_min_)[:].float()
            self.lr = torch.tensor(Lscaler.data_range_)[:].float()+1e-12
        else:
            raise("Unsupported scaling method")
        
        
        self.n_max = self.samples[0][1].shape[0]
        self.n_dist = np.histogram([int(self.samples[i][-2]) for i in train_set],self.n_max+1,range=(0,self.n_max+1),density=True)[0]

        if split == 'train':
            self.compute_mmd_statistics([self.samples[i] for i in train_set], [self.samples[i] for i in test_set])
            self.samples = [self.samples[i] for i in train_set]
        elif split == 'train_train':            
            self.compute_mmd_statistics([self.samples[i] for i in train_train_set], [self.samples[i] for i in test_set])
            self.samples = [self.samples[i] for i in train_train_set]
        elif split == 'train_val':
            self.samples = [self.samples[i] for i in train_val_set]
        elif split == 'test':
            self.samples = [self.samples[i] for i in test_set]
        else:
            assert split=='all'
            
        self.extra_data = False

        ########################## prefetch #####################################
        self.prefetched = []
        for idx in range(len(self.samples)):
            class_id, eigevc_tensor, eigva_tensor, lap_tensor,edge_labels,n_nodes,A = self.samples[idx] 
        
            eigevc_tensor,eigva_tensor = self.scale_xy(eigevc_tensor,eigva_tensor)
    
            
            node_mask = torch.zeros(eigevc_tensor.shape[0])
            node_mask[:n_nodes] = 1
            eigevc_tensor[n_nodes:,:] = 0
            
            evec_mask = torch.ones(eigevc_tensor.shape[-1])
           
            
            if n_nodes<self.point_dim:
                zero_pad = self.point_dim-n_nodes
                eigevc_tensor[:,:zero_pad]=0
                eigva_tensor[:zero_pad]=0
                evec_mask[:zero_pad]=0
    
            E = torch.tensor(0)
            if edge_labels is not None:
                E = torch.zeros(node_mask.shape[0],node_mask.shape[0],self.edge_features) 
                for (i,j),v in edge_labels:
                    E[i,j,v]=1
                    E[j,i,v]=1

            self.prefetched.append( (eigevc_tensor.to(device), eigva_tensor.to(device), node_mask.to(device), evec_mask.to(device), E, class_id[None,:],lap_tensor,n_nodes,A[None,:]) )
            # if self.extra_data:
            #     return eigevc_tensor, eigva_tensor, node_mask, evec_mask, E, class_id[None,:],lap_tensor,n_nodes,A[None,:]
            # return eigevc_tensor, eigva_tensor, node_mask, evec_mask
        
    def compute_mmd_statistics(self,train_set,test_set):
        
        # print("compute graphs statistics")
        compute_emd=False
#         if len(train_set)>500:
#             compute_emd=True
            
#         #compute metrics
#         graph_test_list = [] #should be on test set graphs
#         for jj in np.random.permutation(len(test_set))[:100]:
#             laplacian_matrix = np.array(test_set[jj][3].cpu())[:test_set[jj][4],:test_set[jj][4]]
#             Aori = np.copy(laplacian_matrix)
#             np.fill_diagonal(Aori,0)
#             Aori= Aori*(-1)
#             graph_test_list.append(nx.from_numpy_array(Aori)) 

#         graph_train_list = []
#         for jj in np.random.permutation(len(train_set))[:100]:
#             laplacian_matrix = np.array(train_set[jj][3].cpu())[:train_set[jj][4],:train_set[jj][4]]
#             Aori = np.copy(laplacian_matrix)
#             np.fill_diagonal(Aori,0)
#             Aori= Aori*(-1)
#             graph_train_list.append(nx.from_numpy_array(Aori)) 

#         print("computing degree")        
#         self.degree = degree_stats( graph_test_list,graph_train_list, compute_emd=compute_emd)
#         print("computing cluster")
#         self.cluster = clustering_stats( graph_test_list,graph_train_list, compute_emd=compute_emd)
#         print("computing spectral")
#         self.spectral = spectral_stats(graph_test_list, graph_train_list, compute_emd=compute_emd)

        MAX_GRAPHS = 10000
        train_set = [train_set[i] for i in np.random.permutation(len(train_set))[:MAX_GRAPHS]]
        test_set = [test_set[i] for i in np.random.permutation(len(test_set))[:MAX_GRAPHS]]
        
        adj_list_train = [g[-1][:g[-2]][:,:g[-2]].cpu() for g in train_set]
        adj_list_test = [g[-1][:g[-2]][:,:g[-2]].cpu() for g in test_set]

        adj_list_train = [a[m,:][:,m] for a,m in zip(adj_list_train,[z.sum(-1)>0 for z in adj_list_train])] #remove isolated
        adj_list_test = [a[m,:][:,m] for a,m in zip(adj_list_test,[z.sum(-1)>0 for z in adj_list_test])] #remove isolated

        ########################### dataset stats #####################
        self.degree = degree_stats( adj_list_test, adj_list_train, compute_emd=compute_emd)
        # print("computing degree: ",self.degree)        
        self.cluster = clustering_stats( adj_list_test, adj_list_train, compute_emd=compute_emd)
        # print("computing cluster: ",self.cluster)
        self.spectral = spectral_stats(adj_list_test, adj_list_train, compute_emd=compute_emd)
        # print("computing spectral: ",self.spectral)


    def __len__(self):
        return len(self.samples)
    
    def sample_n_nodes(self, n):
        return np.random.choice(self.n_max+1, n, p=self.n_dist)
        
    def get_extra_data(self, flag=True):
        self.extra_data = flag
        
    def __getitem__(self, idx):
        if self.extra_data:
            return self.prefetched[idx]
        else:
            return self.prefetched[idx][:4]
 
def n_community(num_communities, max_nodes, p_inter=0.05):
    assert num_communities > 1
    
    one_community_size = max_nodes // num_communities
 
    c_sizes = [one_community_size] * num_communities
    total_nodes = one_community_size * num_communities
    
    """ 
    here we calculate `p_make_a_bridge` so that `p_inter = \mathbb{E}(Number_of_bridge_edges) / Total_number_of_nodes `
    
    To make it more clear: 
    let `M = num_communities` and `N = one_community_size`, then
    
    ```
    p_inter
    = \mathbb{E}(Number_of_bridge_edges) / Total_number_of_nodes
    = (p_make_a_bridge * C_M^2 * N^2) / (MN)  # see the code below for this derivation
    = p_make_a_bridge * (M-1) * N / 2
    ```
    
    so we have:
    """
    p_make_a_bridge = p_inter * 2 / ((num_communities - 1) * one_community_size)
    
#     print(num_communities, total_nodes, end=' ')
    graphs = [nx.gnp_random_graph(c_sizes[i], 0.7, seed=i) for i in range(len(c_sizes))]

    G = nx.disjoint_union_all(graphs)
#     communities = list(nx.connected_component_subgraphs(G))
    communities = list(G.subgraph(c) for c in nx.connected_components(G))
    add_edge = 0
    for i in range(len(communities)):
        
        subG1 = communities[i]
         
        nodes1 = list(subG1.nodes())
        for j in range(i + 1, len(communities)):  # loop for C_M^2 times
            subG2 = communities[j]
            nodes2 = list(subG2.nodes())
            has_inter_edge = False
            for n1 in nodes1:  # loop for N times
                for n2 in nodes2:  # loop for N times
                    if np.random.rand() < p_make_a_bridge:
                        G.add_edge(n1, n2)
                        has_inter_edge = True
                        add_edge += 1
            if not has_inter_edge:
                G.add_edge(nodes1[0], nodes2[0])
                add_edge += 1
#     print('connected comp: ', len(list(nx.connected_component_subgraphs(G))),
#           'add edges: ', add_edge)
#     print(G.number_of_edges())
    return G
