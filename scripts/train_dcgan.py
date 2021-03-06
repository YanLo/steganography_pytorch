import os
import argparse
import numpy as np

from tqdm import tqdm
from torch.optim import Adam
from typing import Sequence
from dpipe.io import save_numpy
from dpipe.train.logging import TBLogger

from sgan.utils import *
from sgan.modules import *
from sgan.data import CelebDataset, DataBatchIterator
from sgan.utils import process_batch, generate_noise, inference_step, to_numpy, save_torch


def run_experiment(*, device, download: bool, n_epoch: int, batch_size: int, n_noise_channels: int
                   , data_path: str, experiment_path: str):
    # path to save everything related to experiment
    data_path = Path(data_path).expanduser()
    experiment_path = Path(experiment_path).expanduser()
    # dataset and batch iterator
    dataset = CelebDataset(root=data_path, download=download)
    indices = list(range(len(dataset)))
    train_iterator = DataBatchIterator(dataset, indices, batch_size=batch_size)
    # models
    generator = Generator(in_channels=n_noise_channels).to(device)
    discriminator = Discriminator().to(device)
    generator.apply(init_weights)
    discriminator.apply(init_weights)

    # TODO: remove hardcode
    optimizer_parameters = dict(lr=1e-4, betas=(0.5, 0.99))
    generator_opt = Adam(generator.parameters(), **optimizer_parameters)
    discriminator_opt = Adam(discriminator.parameters(), **optimizer_parameters)

    fixed_noise = torch.randn(64, n_noise_channels, 1, 1, device=device)

    def predict_on_fixed_noise(epoch, prefix='fixed_noise', compression=1):
        predict = to_numpy(inference_step(fixed_noise, generator))
        os.makedirs(experiment_path / prefix, exist_ok=True)
        save_numpy(predict, experiment_path / prefix / f'{epoch}.npy.gz', compression=compression)

    def save_models(epoch):
        os.makedirs(experiment_path / f'generator/', exist_ok=True)
        os.makedirs(experiment_path / f'discriminator', exist_ok=True)
        save_torch(generator, experiment_path / f'generator/generator_{epoch}')
        save_torch(discriminator, experiment_path / f'discriminator/discriminator_{epoch}')

    logger = TBLogger(experiment_path / 'logs')
    epoch_callbacks = [predict_on_fixed_noise, save_models]

    train_dcgan(
        generator=generator,
        generator_opt=generator_opt,
        discriminator=discriminator,
        discriminator_opt=discriminator_opt,
        train_iterator=train_iterator,
        device=device,
        n_epoch=n_epoch,
        n_noise_channels=n_noise_channels,
        callbacks=epoch_callbacks,
        logger=logger
    )


def train_dcgan(*, generator, discriminator, train_iterator, device, n_epoch, generator_opt,
                discriminator_opt, n_noise_channels, callbacks: Sequence[Callable] = None, logger: TBLogger):
    generator = generator.to(device)
    discriminator = discriminator.to(device)
    criterion = F.binary_cross_entropy_with_logits

    callbacks = callbacks or []
    for epoch in tqdm(range(n_epoch)):
        generator_losses = []
        discriminator_losses_on_real = []
        discriminator_losses_on_fake = []

        with train_iterator as iterator:
            for real_batch, _ in iterator:
                real_batch = transform_gan(real_batch)
                batch_size = len(real_batch)
                discriminator_opt.zero_grad()
                # train discriminator on real
                real_loss = process_batch(real_batch, torch.ones(batch_size, 1, 1, 1), discriminator, criterion)
                # train discriminator on fake
                noise = generate_noise(batch_size, n_noise_channels, device)
                fake_batch = generator(noise)
                fake_loss = process_batch(fake_batch.detach(), torch.zeros(batch_size, 1, 1, 1), discriminator,
                                          criterion)
                discriminator_opt.step()
                # train generator
                generator_opt.zero_grad()
                target_for_generator = torch.ones(batch_size, 1, 1, 1)
                generator_loss = process_batch(fake_batch, target_for_generator, discriminator, criterion)
                generator_opt.step()

                generator_losses.append(generator_loss)
                discriminator_losses_on_real.append(real_loss)
                discriminator_losses_on_fake.append(fake_loss)

        # run callbacks
        for callback in callbacks:
            callback(epoch)

        losses = {'Generator': np.mean(generator_losses),
                  'Discriminator on fake': np.mean(discriminator_losses_on_fake),
                  'Discriminator on real': np.mean(discriminator_losses_on_real)
                  }
        logger.policies(losses, epoch)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', required=True)
    parser.add_argument('--experiment_path', type=str, required=True)
    parser.add_argument('--download', dest='download', action='store_true')
    parser.add_argument('--no-download', dest='download', action='store_false')

    parser.add_argument('--batch_size', default=128, type=int)
    parser.add_argument('--n_epoch', default=30, type=int)
    parser.add_argument('--n_noise_channels', default=100, type=int)
    parser.add_argument('--data_path', default='~/celeba', type=str)

    args = parser.parse_args()
    run_experiment(**vars(args))


if __name__ == '__main__':
    main()
