import torch
import torch.nn as nn
import torch.nn.functional as F

class SiameseNet(nn.Module):
    '''Simple Siamese Representation Learning Model.
       @paper{
             title={Exploring Simple Siamese Representation Learning},
             author={Xinlei Chen and Kaiming He},
             year={2020},
             }
    '''
    def __init__(self, encoder):
        super(SiameseNet, self).__init__()

        self.encoder = encoder
        self.projector = ProjectionHead(self.encoder.d_output)
        self.predictor = PredictionModel()

    def forward(self, x1, x2):
        h1, h2 = self.encoder(x1), self.encoder(x2)
        #z1, z2 = self.projector(torch.squeeze(h1)), self.projector(torch.squeeze(h2))
        z1, z2 = self.projector(h1.view(h1.shape[0], h1.shape[1])), self.projector(h2.view(h2.shape[0], h2.shape[1]))
        p1, p2 = self.predictor(z1), self.predictor(z2)

        return z1, p1, z2, p2

    def infer(self, x):
        x = self.encoder(x)
        x = self.projector(x.view(x.shape[0], x.shape[1]))
        x = self.predictor(x)
        #return torch.squeeze(x)
        return x

class ProjectionHead(nn.Module):
    '''Projection Head. 3-layer MLP with hidden fc 2048-d.
    '''
    def __init__(self, d_input, d_hidden=2048, d_output=2048):
        super(ProjectionHead, self).__init__()

        self.layer1 = nn.Sequential(
            nn.Linear(d_input, d_hidden),
            nn.BatchNorm1d(d_hidden),
            nn.ReLU(inplace=True)
        )
        self.layer2 = nn.Sequential(
            nn.Linear(d_hidden, d_hidden),
            nn.BatchNorm1d(d_hidden),
            nn.ReLU(inplace=True)
        )
        self.layer3 = nn.Sequential(
            nn.Linear(d_hidden, d_output),
            nn.BatchNorm1d(d_hidden)
        )

    def forward(self, x):
        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        return x

class PredictionModel(nn.Module):
    '''Prediction Model. 2-layer MLP  with input and output 2048-d.
    '''
    def __init__(self, d_input=2048, d_hidden=512, d_output=2048):
        super(PredictionModel, self).__init__()

        self.layer1 = nn.Sequential(
            nn.Linear(d_input, d_hidden),
            nn.BatchNorm1d(d_hidden),
            nn.ReLU(inplace=True)
        )
        self.layer2 = nn.Linear(d_hidden, d_output)

    def forward(self, x):
        x = self.layer1(x)
        x = self.layer2(x)
        return x
