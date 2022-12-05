import torch
import os
import torch.nn as nn
from forward_process import *
from dataset import *

from torch.optim import Adam
from dataset import *
from backbone import *
from noise import *
from visualize import show_tensor_image

from torch.utils.tensorboard import SummaryWriter
from test import *




def build_optimizer(model, config):
    lr = config.model.learning_rate
    weight_decay = config.model.weight_decay
    return Adam(
        model.parameters(), lr=lr, weight_decay=weight_decay
    )

def get_loss(model, constant_dict, x_0, t, config):
    
    # x_noisy, noise = forward_diffusion_sample(x_0, t , constant_dict, config)
    # noise_pred = model(x_noisy, t)
    # loss = F.l1_loss(noise, noise_pred)
    #loss = F.mse_loss(noise, noise_pred)
    # return loss



    cos_loss = torch.nn.CosineSimilarity()
    loss1 = 0
    x_0 = x_0.to(config.model.device)

    x_noisy, noise = forward_diffusion_sample(x_0, t , constant_dict, config)
    noise_pred = model(x_noisy, t)

    posterior_variance_t = get_index_from_list(constant_dict['posterior_variance'], t, noise_pred.shape, config)
    x_prime_noisy = x_noisy -  torch.sqrt(posterior_variance_t) * noise_pred
    x_noisy_for = x_noisy - torch.sqrt(posterior_variance_t) * noise

    feature_extractor = Feature_extractor(config)
    feature_extractor.to(config.model.device)
    F_x_noisy = feature_extractor(x_noisy_for.to(config.model.device))
    F_x_prime_noisy = feature_extractor(x_prime_noisy.to(config.model.device))
    for item in range(len(F_x_noisy)):
        loss1 += torch.mean(1-cos_loss(F_x_noisy[item].view(F_x_noisy[item].shape[0],-1),
                                      F_x_prime_noisy[item].view(F_x_prime_noisy[item].shape[0],-1)))

    return loss1




@torch.no_grad()
def sample_timestep(config, model, constant_dict, x, t):
    """
    Calls the model to predict the noise in the image and returns 
    the denoised image. 
    Applies noise to this image, if we are not in the last step yet.
    """
    betas_t = get_index_from_list(constant_dict['betas'], t, x.shape, config)

    sqrt_one_minus_alphas_cumprod_t = get_index_from_list(
        constant_dict['sqrt_one_minus_alphas_cumprod'], t, x.shape, config
    )
    sqrt_recip_alphas_t = get_index_from_list(constant_dict['sqrt_recip_alphas'], t, x.shape, config)
    
    # Call model (current image - noise prediction)
    model_mean = sqrt_recip_alphas_t * (
        x - betas_t * model(x, t) / sqrt_one_minus_alphas_cumprod_t
    )
    posterior_variance_t = get_index_from_list(constant_dict['posterior_variance'], t, x.shape, config)
    # if t == 0:
    #     return model_mean
    # else:
    noise = get_noise(x, t, config)

    return model_mean + torch.sqrt(posterior_variance_t) * noise 




@torch.no_grad()
def sample_plot_image(model, trainloader, constant_dict, epoch, category, config):
    image = next(iter(trainloader))[0]
    # Sample noise
    trajectoy_steps = torch.Tensor([config.model.test_trajectoy_steps]).type(torch.int64)

    image = forward_diffusion_sample(image, trajectoy_steps, constant_dict, config)[0]
    num_images = 5
    trajectory_steps = config.model.trajectory_steps
    stepsize = int(trajectory_steps/num_images)
    
    
    plt.figure(figsize=(15,15))
    plt.axis('off')
    image_to_show =show_tensor_image(image)
    plt.subplot(1, num_images+1, int(trajectory_steps/stepsize)+1)
    plt.imshow(image_to_show)
    plt.title(trajectory_steps)
    for i in range(0,trajectory_steps-1)[::-1]:
        t = torch.full((1,), i, device=config.model.device, dtype=torch.long)
        image = sample_timestep(config, model, constant_dict, image, t)
        if i % stepsize == 0:
            plt.subplot(1, num_images+1, int(i/stepsize)+1)
            image_to_show =show_tensor_image(image.detach().cpu())
            plt.imshow(image_to_show)
            plt.title(i)
    plt.subplots_adjust(wspace=0.4)
    plt.savefig('results/{}backward_process_after_{}_epochs.png'.format(category, epoch))
    # plt.show()





def trainer(model, constant_dict, config, category):
    with open('readme.txt', 'a') as f:
        f.write(f"\n {category} : ")
    optimizer = build_optimizer(model, config)
    train_dataset = MVTecDataset(
        root= config.data.data_dir,
        category=category,
        input_size= config.data.image_size,
        is_train=True,
    )
    trainloader = torch.utils.data.DataLoader(
        train_dataset,
        batch_size=config.data.batch_size,
        shuffle=True,
        num_workers=config.model.num_workers,
        drop_last=True,
    )

    

    writer = SummaryWriter('runs/DDAD')

    for epoch in range(config.model.epochs):
        for step, batch in enumerate(trainloader):
            
            t = torch.randint(0, config.model.trajectory_steps, (batch[0].shape[0],), device=config.model.device).long()


            optimizer.zero_grad()
            loss = get_loss(model, constant_dict, batch[0], t, config) 
            writer.add_scalar('loss', loss, epoch)

            loss.backward()
            optimizer.step()
            if epoch % 10 == 0 and step == 0:
                print(f"Epoch {epoch} | Loss: {loss.item()}")
                with open('readme.txt', 'a') as f:
                    f.write(f"\n Epoch {epoch} | Loss: {loss.item()}  |   ")
            if epoch %99 == 0 and epoch > 0 and step ==0:
                sample_plot_image(model, trainloader, constant_dict, epoch, category, config)
                validate(model, constant_dict, config, category)


    if config.model.save_model:
        model_save_dir = os.path.join(os.getcwd(), config.model.checkpoint_dir)
        if not os.path.exists(model_save_dir):
            os.mkdir(model_save_dir)
        torch.save(model.state_dict(), os.path.join(config.model.checkpoint_dir, category), #config.model.checkpoint_name
    )

    writer.flush()
    writer.close()