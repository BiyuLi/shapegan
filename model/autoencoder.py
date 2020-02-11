from model import *
from util import standard_normal_distribution

# determine the number of neurons, here 16; 
# if it is too small, the network will not be expressive; if it's too big, it will train slower and you run into risk of overfitting (if there are too many neurons)
AUTOENCODER_MODEL_COMPLEXITY_MULTIPLIER = 32
amcm = AUTOENCODER_MODEL_COMPLEXITY_MULTIPLIER

class Autoencoder(SavableModule):
    def __init__(self, is_variational = True):
        super(Autoencoder, self).__init__(filename="autoencoder-{:d}.to".format(LATENT_CODE_SIZE))

        self.is_variational = is_variational
        if is_variational:
            self.filename = 'variational-' + self.filename

        # this is for 128 resolution; outchannel has to be same as inchannel; to change res, change the layers! (add one layer in encoder, one in decoder; change 128-->256, and input data sdf vols to 256**)
        self.encoder = nn.Sequential(
            nn.Conv3d(in_channels = 1, out_channels = 1 * amcm, kernel_size = 4, stride = 2, padding = 1),
            nn.BatchNorm3d(1 * amcm),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            
            nn.Conv3d(in_channels = 1 * amcm, out_channels = 2 * amcm, kernel_size = 4, stride = 2, padding = 1),
            nn.BatchNorm3d(2 * amcm),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            
            nn.Conv3d(in_channels = 2 * amcm, out_channels = 4 * amcm, kernel_size = 4, stride = 2, padding = 1),
            nn.BatchNorm3d(4 * amcm),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            
            nn.Conv3d(in_channels = 4 * amcm, out_channels = 8 * amcm, kernel_size = 4, stride = 2, padding = 1),
            nn.BatchNorm3d(8 * amcm),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            
            nn.Conv3d(in_channels = 8 * amcm, out_channels = 8 * amcm, kernel_size = 4, stride = 2, padding = 1),
            nn.BatchNorm3d(8 * amcm),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            
            nn.Conv3d(in_channels = 8 * amcm, out_channels = LATENT_CODE_SIZE * 2, kernel_size = 4, stride = 1),
            nn.BatchNorm3d(LATENT_CODE_SIZE * 2),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            
            Lambda(lambda x: x.reshape(x.shape[0], -1)),

            nn.Linear(in_features = LATENT_CODE_SIZE * 2, out_features=LATENT_CODE_SIZE)
        )
        
        if is_variational:
            self.encoder.add_module('vae-bn', nn.BatchNorm1d(LATENT_CODE_SIZE))
            self.encoder.add_module('vae-lr', nn.LeakyReLU(negative_slope=0.2, inplace=True))

            self.encode_mean = nn.Linear(in_features=LATENT_CODE_SIZE, out_features=LATENT_CODE_SIZE)
            self.encode_log_variance = nn.Linear(in_features=LATENT_CODE_SIZE, out_features=LATENT_CODE_SIZE)
        
        self.decoder = nn.Sequential(            
            nn.Linear(in_features = LATENT_CODE_SIZE, out_features=LATENT_CODE_SIZE * 2),
            nn.BatchNorm1d(LATENT_CODE_SIZE * 2),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            
            Lambda(lambda x: x.reshape(-1, LATENT_CODE_SIZE * 2, 1, 1, 1)),

            nn.ConvTranspose3d(in_channels = LATENT_CODE_SIZE * 2, out_channels = 8 * amcm, kernel_size = 4, stride = 1),
            nn.BatchNorm3d(8 * amcm),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),

            nn.ConvTranspose3d(in_channels = 8 * amcm, out_channels = 8 * amcm, kernel_size = 4, stride = 2, padding = 1),
            nn.BatchNorm3d(8 * amcm),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),

            nn.ConvTranspose3d(in_channels = 8 * amcm, out_channels = 4 * amcm, kernel_size = 4, stride = 2, padding = 1),
            nn.BatchNorm3d(4 * amcm),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),

            nn.ConvTranspose3d(in_channels = 4 * amcm, out_channels = 2 * amcm, kernel_size = 4, stride = 2, padding = 1),
            nn.BatchNorm3d(2 * amcm),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),

            nn.ConvTranspose3d(in_channels = 2 * amcm, out_channels = 1 * amcm, kernel_size = 4, stride = 2, padding = 1),
            nn.BatchNorm3d(1 * amcm),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),

            nn.ConvTranspose3d(in_channels = 1 * amcm, out_channels = 1, kernel_size = 4, stride = 2, padding = 1)
        )
        self.cuda()

    def encode(self, x, return_mean_and_log_variance = False, volume=None):
        x = x.reshape((-1, 1, 128, 128, 128))
        x = self.encoder(x)

        if not self.is_variational:
            if volume is not None:
                x[:, 0] = torch.tensor(volume, dtype=torch.float32).to(x.device)
            return x

        mean = self.encode_mean(x).squeeze()
        
        if self.training or return_mean_and_log_variance:
            log_variance = self.encode_log_variance(x).squeeze()
            standard_deviation = torch.exp(log_variance * 0.5)
            eps = standard_normal_distribution.sample(mean.shape).to(x.device)
        
        if self.training:
            x = mean + standard_deviation * eps
        else:
            x = mean

        if volume is not None:
            x[:, 0] = torch.tensor(volume, dtype=torch.float32).to(x.device)

        if return_mean_and_log_variance:
            return x, mean, log_variance
        else:
            return x

    def decode(self, x):
        # if you put in a single latent code, add empty dimension so it becomes 2D tensor
        if len(x.shape) == 1:
            x = x.unsqueeze(dim = 0)  # add batch dimension
        x = self.decoder(x)
        return x.squeeze()

    def forward(self, x, volume=None):
        if not self.is_variational:
            z = self.encode(x, volume=volume)
            print(z[0, :])
            x = self.decode(z)
            return x

        z, mean, log_variance = self.encode(x, return_mean_and_log_variance = True, volume=volume)

        x = self.decode(z)
        return x, mean, log_variance