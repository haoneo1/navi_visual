import os.path as osp
from torchvision.models.resnet import resnet18, ResNet18_Weights
import torch
from torch import nn
from torch.nn import Linear
from roma import special_procrustes, special_gramschmidt
import cv2
import time

class GramSchmidt(nn.Module):

    def __init__(self):
        super().__init__()
    
    def forward(self, x: torch.Tensor):
        assert x.shape[-1] == 9
        x = x.reshape(
            x.shape[:-1] + (3, 2)
        )
        return special_gramschmidt(x)

class Procruste(nn.Module):

    def __init__(self):
        super().__init__()

    def forward(self, x: torch.Tensor):
        assert x.shape[-1] == 9
        x = x.reshape(
            x.shape[:-1] + (3, 3)
        )
        return special_procrustes(x)

def resnet_18_rot(out_dim: int):
    network = resnet18()
    old_fc = network.fc
    new_fc = Linear(old_fc.in_features, out_dim)
    network.fc = new_fc

    if out_dim == 6:
        adapter = GramSchmidt()
    else:
        adapter = Procruste()

    return nn.Sequential(network, adapter)

def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    network = resnet_18_rot(out_dim=9)
    network.load_state_dict(torch.load("best.pth", map_location=device))
    network.eval()
    # print(network)

    time_start = time.perf_counter()

    img = cv2.imread("./083436_063.jpg")
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, (224, 224))
    img = img.transpose(2, 0, 1)
    # print(img.shape)

    img = torch.from_numpy(img).float()
    img = img.to(device)
    img = img.unsqueeze(0)

    y = network(img)

    time_end = time.perf_counter()
    print(f"Time taken: {(time_end - time_start) * 1000:.2f} milliseconds")
    print(y)

if __name__ == "__main__":
    main()